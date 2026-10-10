"""Score raw reading quality separately from schema acceptance and safety failures."""

import argparse
import json
import statistics
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from .benchmark import ROOT, load_cases, save
from .schema import FIELD_KEYS


def normalized(text):
    return ' '.join(text.casefold().split())


def text_metrics(cases, records, text_for):
    edits = characters = 0
    per_case = []
    for case in cases:
        truth = normalized((ROOT / case['transcription']).read_text())
        prediction = normalized(text_for(case, records.get(case['id'])))
        distance = Levenshtein.distance(truth, prediction)
        edits += distance
        characters += len(truth)
        per_case.append(dict(case_id=case['id'], subset=case['subset'],
                             cer=distance / len(truth), edits=distance, characters=len(truth)))
    return dict(character_error_rate=edits / characters, edits=edits,
                characters=characters, cases=per_case)


def read_records(folder):
    return {p.stem: json.loads(p.read_text()) for p in folder.glob('*.json')}


def evaluate(output):
    cases = load_cases()
    labels = json.loads((ROOT / 'data/clinocr/labels.json').read_text())
    report = dict(cases=len(cases), positive_prescription_cases=0,
                  limitation='Synthetic non-prescription smoke test. Positive medication accuracy and ambiguity recall cannot be estimated. Identity labels await independent human legibility review.',
                  normalization='Casefold + whitespace only; reading order and all digits remain significant.',
                  missing_or_failed_transcription='Scored as empty text; never removed from the denominator.')
    raw = {}
    for case in cases:
        path = output / 'vision/raw' / f"{case['id']}.json"
        if path.exists():
            try:
                response = json.loads(path.read_text())
                raw[case['id']] = json.loads(response['choices'][0]['message']['content'])
            except (ValueError, KeyError, IndexError, TypeError):
                pass
    vision = read_records(output / 'vision')
    if vision:
        identity_correct = non_rx_correct = inappropriate_values = 0
        for case in cases:
            doc = raw.get(case['id'], {})
            fields = doc.get('fields', {})
            non_rx_correct += doc.get('documentType') == 'clinical-other'
            for key in FIELD_KEYS[:2]:
                value = fields.get(key, {}).get('value')
                accepted = labels['cases'][case['id']][key]
                identity_correct += value is not None and normalized(value) in [normalized(v) for v in accepted]
            for key in FIELD_KEYS[2:]:
                field = fields.get(key, {})
                inappropriate_values += field.get('value') is not None or bool(field.get('candidates'))
        successful = sum(vision.get(c['id'], {}).get('status') == 'ok' for c in cases)
        timing = [vision[c['id']]['latency_seconds'] for c in cases if c['id'] in vision]
        report['vision'] = dict(
            model=next(iter(vision.values()))['model'], accepted_outputs=successful,
            recorded_cases=sum(c['id'] in vision for c in cases),
            failed_or_rejected_outputs=len(cases) - successful,
            raw_document_classification_correct=non_rx_correct,
            raw_document_classification_total=len(cases),
            raw_identity_fields_correct=identity_correct, raw_identity_fields_total=2 * len(cases),
            raw_inappropriate_order_fields=inappropriate_values,
            raw_order_fields_total=8 * len(cases),
            median_request_seconds=statistics.median(timing),
            billed_cost_usd=None,
            estimated_cost_usd=sum(((r.get('usage') or {}).get('prompt_tokens', 0) * .4
                                    + (r.get('usage') or {}).get('completion_tokens', 0) * 1.6) / 1e6
                                   for r in vision.values()),
            cost_note='Estimate from GPT-4.1-mini catalog rates, not confirmed gateway billing.',
            text=text_metrics(cases, raw, lambda c, r: (r or {}).get('transcription', '')),
        )
    for variant in ('original', 'enhanced'):
        records = read_records(output / 'paddle' / variant)
        if records:
            report['paddle_' + variant] = dict(
                recorded_cases=sum(c['id'] in records for c in cases),
                successful=sum(records.get(c['id'], {}).get('status') == 'ok' for c in cases),
                text=text_metrics(cases, records, lambda c, r: (r or {}).get('transcription', '')),
                median_request_seconds=statistics.median(r['latency_seconds'] for r in records.values()),
            )
    if 'paddle_original' in report and 'paddle_enhanced' in report:
        before = {r['case_id']: r['cer'] for r in report['paddle_original']['text']['cases']}
        after = {r['case_id']: r['cer'] for r in report['paddle_enhanced']['text']['cases']}
        report['enhancement_comparison'] = dict(
            improved=sum(after[k] < v for k, v in before.items()),
            worsened=sum(after[k] > v for k, v in before.items()),
            tied=sum(after[k] == v for k, v in before.items()),
            character_error_rate_delta=report['paddle_enhanced']['text']['character_error_rate'] - report['paddle_original']['text']['character_error_rate'],
        )
    report['run_complete'] = all(report.get(key, {}).get('recorded_cases') == len(cases)
                                 for key in ('vision', 'paddle_original', 'paddle_enhanced'))
    save(output / 'metrics.json', report)
    print('Saved', output / 'metrics.json')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/baseline')
    evaluate(parser.parse_args().output)
