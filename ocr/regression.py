"""Run/score the gathered ClinOCR non-prescriptions, without inventing positive truth."""

import argparse
import json
import math
import os
import statistics
import time
from collections import Counter
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field

from .benchmark import ROOT, load_cases
from .pipeline import PipelineResult, private_output_path, run_pipeline
from .prism import PrismTracer
from .release import RELEASE_POLICY_VERSION
from .schema import StrictModel
from .verify import PRIMARY_MODEL, PROMPT_VERSION, VERIFIER_MODEL, prepare_image, prompt_hash


class RegressionRecord(StrictModel):
    pipeline: PipelineResult
    processing_seconds: float | None = Field(default=None, ge=0)


def validate_record(record, case, models):
    result = record.pipeline
    if result.input_sha256 != case['sha256'] or result.decision.policy_version != RELEASE_POLICY_VERSION:
        raise ValueError('Cached run uses another input or policy')
    for role, model in zip(('primary', 'verifier'), models, strict=True):
        reading = getattr(result, role)
        if (reading.input_sha256 != case['sha256'] or reading.role != role
                or reading.requested_model != model or reading.prompt_version != PROMPT_VERSION
                or reading.prompt_sha256 != prompt_hash(role)):
            raise ValueError('Cached run uses another input, model, or prompt')


def summarize(cases, records, models=(PRIMARY_MODEL, VERIFIER_MODEL)):
    if any(c['documentType'] != 'clinical-other' for c in cases):
        raise ValueError('This evaluator only supports the gathered non-prescription regression set')
    rows, timings, failures = [], [], Counter()
    states = Counter()
    model_metrics = {role: dict(model=model, recorded=0, schema_valid=0,
                               validated_non_prescription=0, errors={},
                               reported_prompt_tokens=0, reported_completion_tokens=0,
                               usage_records=0)
                     for role, model in zip(('primary', 'verifier'), models, strict=True)}
    for case in cases:
        record = records.get(case['id'])
        if record is None:
            rows.append(dict(id=case['id'], input_sha256=case['sha256'], status='unprocessed'))
            continue
        validate_record(record, case, models)
        result = record.pipeline
        states[result.decision.status] += 1
        if record.processing_seconds is not None:
            timings.append(record.processing_seconds)
        reasons = sorted({r.code for r in result.decision.document_reasons} | {
            r.code for reasons in result.decision.field_reasons.values() for r in reasons})
        row = dict(id=case['id'], input_sha256=case['sha256'], status=result.decision.status,
                   reason_codes=reasons, processing_seconds=record.processing_seconds)
        for role in ('primary', 'verifier'):
            reading = getattr(result, role)
            metrics = model_metrics[role]
            metrics['recorded'] += 1
            metrics['schema_valid'] += reading.status == 'ok'
            metrics['validated_non_prescription'] += bool(
                reading.reading and reading.reading.documentType == 'clinical-other')
            if reading.error:
                metrics['errors'][reading.error] = metrics['errors'].get(reading.error, 0) + 1
                failures[reading.error] += 1
            usage = reading.usage or {}
            if all(isinstance(usage.get(k), int) and not isinstance(usage[k], bool) and usage[k] >= 0
                   for k in ('prompt_tokens', 'completion_tokens')):
                metrics['usage_records'] += 1
                metrics['reported_prompt_tokens'] += usage['prompt_tokens']
                metrics['reported_completion_tokens'] += usage['completion_tokens']
            row[role + '_status'] = reading.status
            row[role + '_error'] = reading.error
        rows.append(row)
    total = len(cases)
    recorded = sum(states.values())
    blocked = states['exception'] + states['rejected']
    return dict(
        summary_version='clinocr-regression-v1', policy_version=RELEASE_POLICY_VERSION,
        synthetic=True, expected_cases=total, recorded_cases=recorded,
        positive_prescription_cases=0, complete=recorded == total,
        decisions={key: states[key] for key in ('auto-released', 'exception', 'rejected')},
        non_prescription_blocked=blocked,
        non_prescription_block_rate=blocked / total if total else None,
        inappropriate_releases=states['auto-released'],
        inappropriate_release_rate_observed=states['auto-released'] / recorded if recorded else None,
        whole_order_accuracy=None, critical_false_accept_rate=None, supported_prescription_coverage=None,
        model_reads=model_metrics, model_errors=dict(failures),
        processing_latency=dict(measured_cases=len(timings),
                                p50_seconds=statistics.median(timings) if timings else None,
                                p95_seconds=sorted(timings)[math.ceil(.95 * len(timings)) - 1] if timings else None,
                                note='Ingestion + two concurrent readings + gate; excludes artifact writes. P95 is nearest rank.'),
        billed_cost_usd=None,
        limitation='Non-prescription regression only. Unknown quality/OCR/support checks block release. '
                   'Blocking is not evidence of prescription accuracy, selectivity, calibration, or clinical safety. '
                   'Missing cases stay in the block-rate denominator; missing usage is not a free request.',
        cases=rows,
    )


def save_private(path, value, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x' if exclusive else 'w', encoding='utf-8') as handle:
        os.chmod(path, 0o600)
        handle.write(value.model_dump_json(indent=2) if isinstance(value, StrictModel)
                     else json.dumps(value, indent=2))
        handle.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Make paid model calls for missing cases only')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/regression/clinocr-blind-v1')
    args = parser.parse_args()
    output = private_output_path(args.output)
    cases = load_cases()
    config = {**dotenv_values(ROOT / '.env'), **os.environ}
    tracer = PrismTracer.from_values(config)
    models = (config.get('NICRRON_MODEL', PRIMARY_MODEL), config.get('NICRRON_VERIFIER_MODEL', VERIFIER_MODEL))
    key = config.get('NICRRON_API_KEY')
    if args.run and not key:
        parser.error('Set NICRRON_API_KEY before --run')
    records = {}
    # Validate every existing receipt before spending credits; never rerun validation failures.
    for case in cases:
        path = output / (case['id'] + '.json')
        if path.exists():
            record = RegressionRecord.model_validate_json(path.read_text())
            validate_record(record, case, models)
            records[case['id']] = record
    for case in cases:
        if not args.run or case['id'] in records:
            continue
        started = time.perf_counter()
        image = prepare_image((ROOT / case['image']).read_bytes())
        pipeline = run_pipeline(image, api_key=key, primary_model=models[0], verifier_model=models[1],
                                tracer=tracer)
        record = RegressionRecord(pipeline=pipeline, processing_seconds=round(time.perf_counter() - started, 3))
        save_private(output / (case['id'] + '.json'), record, exclusive=True)
        records[case['id']] = record
        print(case['id'], pipeline.decision.status, flush=True)
    report = summarize(cases, records, models)
    save_private(output / 'metrics.json', report)
    print(json.dumps({key: report[key] for key in (
        'recorded_cases', 'expected_cases', 'decisions', 'non_prescription_block_rate')}))


if __name__ == '__main__':
    main()
