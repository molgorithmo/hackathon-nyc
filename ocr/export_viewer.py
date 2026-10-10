"""Export an allowlisted, read-only snapshot for the local React results viewer."""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def vision_view(record, raw):
    record = record or {}
    extraction = record.get('extraction')
    if extraction is None and raw:
        try:
            extraction = json.loads(raw['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            extraction = None
    extraction = extraction if isinstance(extraction, dict) else {}
    # Rejected suggestions remain rejected even when their raw JSON can be read.
    return dict(status=record.get('status', 'unavailable'), error=record.get('error'),
                latencySeconds=record.get('latency_seconds'),
                documentType=extraction.get('documentType'),
                transcription=extraction.get('transcription', ''),
                fields=extraction.get('fields'), notes=extraction.get('notes', []))


def ocr_view(record):
    if record is None:
        return None
    return {key: record.get(key, default) for key, default in (
        ('status', 'unavailable'), ('transcription', ''), ('tokens', []))}


def regression_view(directory, cases):
    # Recompute the public summary from image-bound receipts; never export raw readings.
    from .regression import RegressionRecord, summarize
    from .verify import PRIMARY_MODEL, VERIFIER_MODEL

    report = read_json(directory / 'metrics.json')
    if report is None:
        raise ValueError('Score the regression before exporting it')
    models = tuple(report['model_reads'][role]['model'] for role in ('primary', 'verifier'))
    if models != (PRIMARY_MODEL, VERIFIER_MODEL):
        raise ValueError('Viewer regression expects the pinned primary and verifier models')
    records = {}
    for case in cases:
        path = directory / (case['id'] + '.json')
        if path.exists():
            records[case['id']] = RegressionRecord.model_validate_json(path.read_text())
    return summarize(cases, records, models)


def words_view(directory, target):
    from .benchmark_words import DATA, load_sample, report_words

    cases, sample_hash = load_sample()
    report = report_words(cases, sample_hash, directory)
    images = target / 'rxwords'
    images.mkdir(parents=True, exist_ok=True)
    report['images'] = {}
    for case in cases:
        name = case['id'] + '.jpg'
        shutil.copyfile(DATA / case['image'], images / name)
        report['images'][case['id']] = '/run/rxwords/' + name
    return report


def export(regression=None, words=None):
    baseline = ROOT / 'artifacts/baseline'
    metrics = read_json(baseline / 'metrics.json')
    manifest = read_json(ROOT / 'data/clinocr/manifest.json')
    if metrics is None or manifest is None:
        raise ValueError('Run the benchmark and evaluator before exporting the viewer')
    target = ROOT / 'public/run'
    target.mkdir(parents=True, exist_ok=True)
    cases = []
    for case in manifest['cases']:
        case_id = case['id']
        source = (ROOT / case['image']).resolve()
        reference = (ROOT / case['transcription']).resolve()
        if (Path(case_id).name != case_id or
                not source.is_relative_to(ROOT / 'data/clinocr/images') or
                not reference.is_relative_to(ROOT / 'data/clinocr/transcriptions')):
            raise ValueError('Unexpected dataset path')
        shutil.copyfile(source, target / f'{case_id}.jpg')
        with Image.open(source) as image:
            width, height = image.size
        enhanced = baseline / f'{case_id}_enhanced.png'
        enhanced_width = enhanced_height = None
        if enhanced.exists():
            shutil.copyfile(enhanced, target / enhanced.name)
            with Image.open(enhanced) as image:
                enhanced_width, enhanced_height = image.size
        cases.append(dict(
            id=case_id, subset=case['subset'],
            originalImage=f'/run/{case_id}.jpg',
            enhancedImage=f'/run/{enhanced.name}' if enhanced.exists() else None,
            imageWidth=width, imageHeight=height,
            enhancedWidth=enhanced_width, enhancedHeight=enhanced_height,
            reference=reference.read_text(),
            vision=vision_view(read_json(baseline / 'vision' / f'{case_id}.json'),
                               read_json(baseline / 'vision/raw' / f'{case_id}.json')),
            paddleOriginal=ocr_view(read_json(baseline / 'paddle/original' / f'{case_id}.json')),
            paddleEnhanced=ocr_view(read_json(baseline / 'paddle/enhanced' / f'{case_id}.json'))))
    snapshot = dict(generatedAt=datetime.now(timezone.utc).isoformat(), metrics=metrics, cases=cases)
    if regression is not None:
        snapshot['regression'] = regression_view(regression, manifest['cases'])
    if words is not None:
        snapshot['words'] = words_view(words, target)
    temporary = target / 'results.json.tmp'
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False))
    temporary.replace(target / 'results.json')
    print(f'Exported {len(cases)} cases to public/run/results.json (no model calls)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--regression', type=Path, help='Include a scored blind-regression directory')
    parser.add_argument('--words', type=Path, help='Include the frozen RxHandBD word benchmark')
    args = parser.parse_args()
    export(args.regression, args.words)
