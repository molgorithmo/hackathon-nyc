import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from ocr.benchmark_words import (
    DATA, MODELS, PROMPT_HASH, VERSION, WordReading, read_word, score_words,
    select_sample, validate_record, word_payload,
    word_agreement,
)
from ocr.verify import prepare_image
from ocr.export_viewer import words_view


class WordBenchmarkTests(unittest.TestCase):
    def test_sample_is_deterministic_order_independent_and_test_only(self):
        cases = [dict(id=str(i), sha256=str(i), split='test' if i < 8 else 'train')
                 for i in range(10)]
        before = copy.deepcopy(cases)
        selected = select_sample(cases, 5)
        self.assertEqual(selected, select_sample(list(reversed(cases)), 5))
        self.assertTrue(all(c['split'] == 'test' for c in selected))
        self.assertEqual(before, cases)
        with self.assertRaises(ValueError):
            select_sample(cases, 9)

    def test_missing_failures_and_abstentions_stay_in_denominator(self):
        cases = [dict(id=str(i), text='25 mg') for i in range(4)]
        records = {
            '0': dict(status='ok', text='25 mg', reading_status='readable', latency_seconds=1),
            '1': dict(status='error', text='25 mg', latency_seconds=2),
            '2': dict(status='ok', text=None, reading_status='ambiguous', latency_seconds=3),
        }
        result = score_words(cases, records)
        self.assertEqual(result['exact_match_rate'], .25)
        self.assertEqual(result['character_error_rate'], .75)
        self.assertEqual((result['failed'], result['abstained'], result['missing']), (1, 1, 1))
        self.assertIsNone(result['billed_cost_usd'])
        self.assertEqual(result['reported_usage']['receipts'], 0)

    def test_normalization_preserves_strength_digits_and_strict_case_difference(self):
        cases = [dict(id='a', text='Napa 25 mg')]
        records = {'a': dict(status='ok', text='napa  25 mg', latency_seconds=1)}
        result = score_words(cases, records)
        self.assertEqual(result['exact_match_rate'], 1)
        self.assertEqual(result['strict_exact_match_rate'], 0)
        records['a']['text'] = 'Napa 75 mg'
        self.assertEqual(score_words(cases, records)['exact_match_rate'], 0)

    def test_uncertainty_cannot_select_a_word(self):
        for status, text in [('ambiguous', '25 mg'), ('unreadable', 'drug'), ('readable', ' ')]:
            with self.subTest(status=status), self.assertRaises(ValidationError):
                WordReading(status=status, text=text)

    def test_agreement_counts_matching_wrong_words_without_counting_abstentions(self):
        rows = [dict(id='a', status='ok', prediction='75 mg', exact_match=False),
                dict(id='b', status='ok', prediction=None, exact_match=False),
                dict(id='c', status='ok', prediction='Napa', exact_match=True)]
        result = word_agreement(rows, copy.deepcopy(rows))
        self.assertEqual(result, dict(agreeing_nonblank_crops=2, agreeing_matching_label=1,
                                      agreeing_mismatching_label=1))

    def test_receipts_are_bound_to_sample_model_prompt_and_image(self):
        case = dict(id='P0001', sha256='abc')
        record = dict(case_id='P0001', image_sha256='abc', engine='mini',
                      model=MODELS['mini'], version=VERSION, sample_hash='sample',
                      prompt_hash=PROMPT_HASH, status='ok', text='25 mg', reading_status='readable')
        validate_record(record, case, 'mini', 'sample')
        for key in ('image_sha256', 'model', 'sample_hash', 'prompt_hash'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_record({**record, key: 'wrong'}, case, 'mini', 'sample')

    def test_requests_contain_image_only_and_no_reference_labels(self):
        image = prepare_image((DATA / 'images/test/P0001.jpg').read_bytes())
        payload = word_payload(image, MODELS['mini'])
        self.assertEqual(len(payload['messages']), 2)
        self.assertEqual([c['type'] for c in payload['messages'][1]['content']], ['image_url'])
        self.assertNotIn('Nexcital', json.dumps(payload))

    def test_invalid_or_truncated_model_reading_is_preserved_without_repair(self):
        case = dict(id='P0001', image='images/test/P0001.jpg', text='SECRET_REFERENCE')
        for finish, status in [('stop', 'ambiguous'), ('length', 'readable')]:
            raw = dict(model=MODELS['mini'], choices=[dict(finish_reason=finish,
                       message=dict(content=json.dumps(dict(status=status, text='25 mg'))))])

            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self): return json.dumps(raw).encode()

            with self.subTest(finish=finish), patch('ocr.benchmark_words.urllib.request.urlopen', return_value=Response()):
                result = read_word(case, 'mini', 'not-a-real-key', 'sample')
                self.assertEqual(result['status'], 'error')
                self.assertIsNone(result['text'])
                self.assertEqual(result['raw_response'], raw)

    def test_word_export_recomputes_metrics_without_private_receipts(self):
        from pathlib import Path
        from ocr.benchmark_words import load_sample
        from ocr.regression import save_private

        cases, sample_hash = load_sample()
        case = cases[0]
        with tempfile.TemporaryDirectory() as directory:
            output, target = Path(directory) / 'receipts', Path(directory) / 'public'
            record = dict(case_id=case['id'], image_sha256=case['sha256'], engine='mini',
                          model=MODELS['mini'], version=VERSION, sample_hash=sample_hash,
                          prompt_hash=PROMPT_HASH, status='ok', text='visible text',
                          reading_status='readable', latency_seconds=1,
                          raw_response={'secret': 'DO_NOT_EXPORT'})
            save_private(output / 'mini' / (case['id'] + '.json'), record)
            report = words_view(output, target)
            self.assertEqual(report['engines']['mini']['recorded'], 1)
            self.assertEqual(report['engines']['mini']['missing'], 99)
            self.assertNotIn('DO_NOT_EXPORT', json.dumps(report))
            self.assertNotIn('raw_response', json.dumps(report))
            self.assertIn('P0049', report['reference_warning'])
            self.assertEqual(len(list((target / 'rxwords').glob('*.jpg'))), 100)


if __name__ == '__main__':
    unittest.main()
