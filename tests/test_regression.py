import copy
import json
import tempfile
import unittest
from pathlib import Path

from ocr.export_viewer import regression_view
from ocr.pipeline import run_pipeline
from ocr.regression import RegressionRecord, save_private, summarize
from ocr.release import AcceptedOrder, ReleaseDecision
from ocr.verify import (
    DocumentReading, PRIMARY_MODEL, VERIFIER_MODEL, ReadingResult, prepare_image, prompt_hash,
)

ROOT = Path(__file__).resolve().parents[1]


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = prepare_image((ROOT / 'data/clinocr/images/template_8_sample_2_normal.jpg').read_bytes())
        cls.case = dict(id='unit-case', sha256=cls.image.sha256, documentType='clinical-other')

    def record(self):
        payload = json.loads((ROOT / 'tests/fixtures/release_prescription.json').read_text())
        payload.update(documentType='clinical-other', orderCount=0)
        for field in payload['fields'].values():
            field.update(value=None, sourceText=None, status='missing')

        def reader(image, role, model, api_key):
            return ReadingResult(role=role, call_id=role, input_sha256=image.sha256,
                                 prompt_sha256=prompt_hash(role), requested_model=model,
                                 status='ok', finish_reason='stop', latency_seconds=1.0,
                                 reading=DocumentReading.model_validate(copy.deepcopy(payload)))
        result = run_pipeline(self.image, api_key='unused', reader=reader)
        return RegressionRecord(pipeline=result, processing_seconds=2.0)

    def test_missing_cases_do_not_become_successfully_blocked(self):
        result = summarize([self.case], {})
        self.assertEqual(result['recorded_cases'], 0)
        self.assertEqual(result['non_prescription_block_rate'], 0)
        self.assertIsNone(result['inappropriate_release_rate_observed'])
        self.assertIsNone(result['whole_order_accuracy'])
        self.assertFalse(result['complete'])

    def test_negative_only_set_does_not_claim_positive_accuracy_or_coverage(self):
        record = self.record()
        before = record.model_dump_json()
        result = summarize([self.case], {'unit-case': record})
        self.assertEqual(result['decisions']['rejected'], 1)
        self.assertEqual(result['non_prescription_block_rate'], 1)
        self.assertIsNone(result['whole_order_accuracy'])
        self.assertIsNone(result['critical_false_accept_rate'])
        self.assertIsNone(result['supported_prescription_coverage'])
        self.assertEqual(result['model_reads']['primary']['usage_records'], 0)
        self.assertIsNone(result['billed_cost_usd'])
        self.assertEqual(before, record.model_dump_json())

    def test_positive_truth_or_wrong_image_run_cannot_enter_negative_report(self):
        with self.assertRaises(ValueError):
            summarize([{**self.case, 'documentType': 'prescription'}], {})
        with self.assertRaises(ValueError):
            summarize([{**self.case, 'sha256': '0' * 64}], {'unit-case': self.record()})

    def test_inappropriate_release_is_counted_and_no_private_fields_are_exported(self):
        record = self.record()
        payload = json.loads((ROOT / 'tests/fixtures/release_prescription.json').read_text())
        order = AcceptedOrder(**{k: f['value'] for k, f in payload['fields'].items()})
        record.pipeline.decision = ReleaseDecision(status='auto-released', accepted_order=order,
                                                   document_reasons=[], field_reasons={})
        result = summarize([self.case], {'unit-case': record})
        self.assertEqual(result['inappropriate_releases'], 1)
        self.assertEqual(result['non_prescription_block_rate'], 0)
        self.assertEqual(result['inappropriate_release_rate_observed'], 1)
        public = json.dumps(result)
        self.assertNotIn('Test Person', public)
        self.assertNotIn('raw_response', public)

    def test_partial_run_and_missing_timings_remain_explicit(self):
        record = self.record()
        record.processing_seconds = None
        result = summarize([self.case, {**self.case, 'id': 'missing'}], {'unit-case': record})
        self.assertEqual(result['non_prescription_block_rate'], .5)
        self.assertEqual(result['processing_latency']['measured_cases'], 0)
        self.assertIsNone(result['processing_latency']['p95_seconds'])

    def test_viewer_recomputes_summary_and_rejects_foreign_image_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            record = self.record()
            report = summarize([self.case], {'unit-case': record})
            report['private'] = 'must not export'
            report['decisions']['auto-released'] = 99
            save_private(path / 'metrics.json', report)
            save_private(path / 'unit-case.json', record)
            public = regression_view(path, [self.case])
            self.assertEqual(public['decisions']['auto-released'], 0)
            self.assertNotIn('private', public)
            self.assertNotIn('raw_response', json.dumps(public))
            with self.assertRaises(ValueError):
                regression_view(path, [{**self.case, 'sha256': '0' * 64}])


if __name__ == '__main__':
    unittest.main()
