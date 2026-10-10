"""Run two blind readings of one image and route through the deterministic gate."""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field

from .release import FieldKey, ReleaseDecision, ReleaseSignals, evaluate_release
from .schema import StrictModel
from .verify import (
    PRIMARY_MODEL, PROMPT_VERSION, VERIFIER_MODEL, PreparedImage, ReadingResult,
    prepare_image, prompt_hash, read_document,
)


class EvidenceChecks(StrictModel):
    input_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    ocr_checked: bool | None = None
    ocr_contradictions: dict[FieldKey, str] = Field(default_factory=dict)
    image_quality_passed: bool | None = None
    document_supported: bool | None = None
    in_distribution: bool | None = None


class PipelineResult(StrictModel):
    input_sha256: str
    primary: ReadingResult
    verifier: ReadingResult
    signals: ReleaseSignals
    decision: ReleaseDecision


def run_pipeline(image: PreparedImage, *, api_key: str,
                 primary_model: str = PRIMARY_MODEL, verifier_model: str = VERIFIER_MODEL,
                 checks: EvidenceChecks | None = None, reader=read_document, tracer=None) -> PipelineResult:
    checks = checks or EvidenceChecks(input_sha256=image.sha256)
    if checks.input_sha256 != image.sha256:
        raise ValueError('Evidence checks belong to a different input image')
    # Validate contradiction explanations before making any paid model calls.
    evidence = ReleaseSignals(**checks.model_dump(exclude={'input_sha256'}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        primary_call = pool.submit(reader, image, role='primary', model=primary_model, api_key=api_key)
        verifier_call = pool.submit(reader, image, role='verifier', model=verifier_model, api_key=api_key)
        primary, verifier = primary_call.result(), verifier_call.result()

    def same_input(result, role, model):
        return (result.input_sha256 == image.sha256 and result.role == role
                and result.requested_model == model and result.prompt_version == PROMPT_VERSION
                and result.prompt_sha256 == prompt_hash(role))

    primary_valid = primary.status == 'ok' and same_input(primary, 'primary', primary_model)
    verifier_valid = verifier.status == 'ok' and same_input(verifier, 'verifier', verifier_model)
    independent = (same_input(primary, 'primary', primary_model)
                   and same_input(verifier, 'verifier', verifier_model)
                   and primary.call_id != verifier.call_id
                   and not (primary.request_id and primary.request_id == verifier.request_id))
    signals = ReleaseSignals(**evidence.model_dump(exclude={
        'primary_complete', 'verifier_complete', 'primary_order_count',
        'verifier_order_count', 'independent_verification'}),
        primary_complete=primary_valid, verifier_complete=verifier_valid,
        primary_order_count=primary.reading.orderCount if primary_valid else None,
        verifier_order_count=verifier.reading.orderCount if verifier_valid else None,
        independent_verification=independent)
    decision = evaluate_release(primary.reading if primary_valid else None,
                                verifier.reading if verifier_valid else None, signals=signals)
    result = PipelineResult(input_sha256=image.sha256, primary=primary, verifier=verifier,
                            signals=signals, decision=decision)
    if tracer is not None:
        try:
            tracer.emit_pipeline(image, result)
        except Exception:
            pass  # Observability failure cannot change the release decision.
    return result


def private_output_path(path: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    output = path.resolve()
    if output.is_relative_to(root) and not output.is_relative_to(root / 'artifacts'):
        raise ValueError('Store receipts under artifacts/ or in a private location outside the project')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--checks', type=Path, help='Image-hash-bound explicit evidence checks; omitted checks block release')
    args = parser.parse_args()
    image = prepare_image(args.image.read_bytes())
    checks = EvidenceChecks.model_validate_json(args.checks.read_text()) if args.checks else None
    if args.output.exists():
        parser.error('Output already exists; choose a new path to preserve the prior run')
    root = Path(__file__).resolve().parents[1]
    try:
        output = private_output_path(args.output)
    except ValueError as exc:
        parser.error(str(exc))
    config = {**dotenv_values(root / '.env'), **os.environ}
    key = config.get('NICRRON_API_KEY')
    if not key:
        parser.error('Set NICRRON_API_KEY in the local .env file')
    from .prism import PrismTracer
    result = run_pipeline(image, api_key=key, tracer=PrismTracer.from_values(config),
                          primary_model=config.get('NICRRON_MODEL', PRIMARY_MODEL),
                          verifier_model=config.get('NICRRON_VERIFIER_MODEL', VERIFIER_MODEL), checks=checks)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        os.chmod(output, 0o600)
        handle.write(result.model_dump_json(indent=2) + '\n')
    # Ordinary console output excludes names, prescriptions, raw responses, and secrets.
    print(json.dumps(dict(status=result.decision.status, policy_version=result.decision.policy_version,
                          primary_status=result.primary.status, primary_error=result.primary.error,
                          verifier_status=result.verifier.status, verifier_error=result.verifier.error)))


if __name__ == '__main__':
    main()
