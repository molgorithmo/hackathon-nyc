import copy
import hashlib
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from ocr.pipeline import EvidenceChecks, private_output_path, run_pipeline
from ocr.schema import FIELD_KEYS
from ocr.verify import (
    DocumentReading, PRIMARY_MODEL, VERIFIER_MODEL, prepare_image, read_document,
    reading_payload,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/release_prescription.json'


def reading_fixture():
    return {**json.loads(FIXTURE.read_text()), 'orderCount': 1}


class Response(io.BytesIO):
    def __init__(self, raw):
        super().__init__(json.dumps(raw).encode())
        self.headers = {}


def response(payload, *, content=None, finish='stop', model=None):
    return Response(dict(model=model or payload['model'].split('/')[-1] + '-2025-04-14',
                         usage=dict(prompt_tokens=100, completion_tokens=100),
                         choices=[dict(finish_reason=finish, message=dict(
                             content=json.dumps(content if content is not None else reading_fixture())))]))


class VerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = prepare_image((ROOT / 'data/clinocr/images/template_8_sample_2_normal.jpg').read_bytes())

    def checks(self, **changes):
        return EvidenceChecks(**{'input_sha256': self.image.sha256, 'ocr_checked': True,
                                 'image_quality_passed': True, 'document_supported': True,
                                 'in_distribution': True, **changes})

    def test_ingestion_validates_content_and_hash_without_transforming_image(self):
        data = self.image.data
        self.assertEqual(self.image.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(self.image.mime_type, 'image/jpeg')
        self.assertEqual(prepare_image(data).data, data)
        for invalid in (b'', b'not an image', data[:100], b'x' * (10 * 1024 * 1024 + 1)):
            with self.subTest(size=len(invalid)), self.assertRaises(ValueError):
                prepare_image(invalid)

    def test_verifier_request_is_blind_even_after_primary_returns_an_answer(self):
        requests = []

        def reply(request, timeout):
            payload = json.loads(request.data)
            requests.append(payload)
            content = reading_fixture()
            content['fields']['drug'].update(value='PRIMARY_ONLY_SENTINEL', sourceText='PRIMARY_ONLY_SENTINEL')
            return response(payload, content=content)

        with patch('ocr.verify.urllib.request.urlopen', side_effect=reply):
            primary = read_document(self.image, role='primary', model=PRIMARY_MODEL, api_key='test-secret')
            verifier = read_document(self.image, role='verifier', model=VERIFIER_MODEL, api_key='test-secret')
        self.assertEqual(primary.status, 'ok')
        self.assertEqual(verifier.status, 'ok')
        self.assertNotEqual(primary.call_id, verifier.call_id)
        self.assertNotIn('PRIMARY_ONLY_SENTINEL', json.dumps(requests[1]))
        self.assertNotIn('test-secret', primary.model_dump_json())
        self.assertNotIn('test-secret', json.dumps(requests))
        self.assertEqual(len(requests[1]['messages']), 2)
        self.assertEqual(requests[0]['messages'][1]['content'][1], requests[1]['messages'][1]['content'][1])

    def test_payload_contains_no_labels_ocr_or_context_and_requires_order_count(self):
        payload = reading_payload(self.image, role='verifier', model=VERIFIER_MODEL)
        self.assertEqual(set(payload), {'model', 'temperature', 'max_tokens', 'messages', 'response_format'})
        self.assertIn('orderCount', payload['response_format']['json_schema']['schema']['required'])
        self.assertEqual(payload['messages'][1]['content'][0]['type'], 'text')
        self.assertNotIn('FILE: context/', json.dumps(payload))
        with self.assertRaises(ValidationError):
            DocumentReading.model_validate(json.loads(FIXTURE.read_text()))

    def test_truncation_refusal_and_model_fallback_never_produce_an_accepted_reading(self):
        for finish, model in (('length', None), ('content_filter', None),
                               ('stop', 'gpt-4.1-mini-2025-04-14')):
            with self.subTest(finish=finish, model=model):
                with patch('ocr.verify.urllib.request.urlopen', side_effect=lambda req, timeout:
                           response(json.loads(req.data), finish=finish, model=model)):
                    result = read_document(self.image, role='verifier', model=VERIFIER_MODEL, api_key='test-secret')
                self.assertEqual(result.status, 'error')
                self.assertIsNone(result.reading)
                self.assertIsNotNone(result.raw_response)

    def test_schema_failure_retains_raw_response_without_repairing_it(self):
        content = reading_fixture()
        content['fields']['strength']['sourceText'] = None
        with patch('ocr.verify.urllib.request.urlopen', side_effect=lambda req, timeout:
                   response(json.loads(req.data), content=content)):
            result = read_document(self.image, role='primary', model=PRIMARY_MODEL, api_key='test-secret')
        self.assertEqual(result.error, 'INVALID_EXTRACTION')
        self.assertIsNone(result.reading)
        raw_content = json.loads(result.raw_response['choices'][0]['message']['content'])
        self.assertIsNone(raw_content['fields']['strength']['sourceText'])

    def test_service_errors_are_explicit_and_do_not_leak_exception_text(self):
        for failure, expected in (
            (urllib.error.HTTPError('https://api.nicrron.ai/', 502, 'test-secret', {}, None), 'GATEWAY_HTTP_502'),
            (TimeoutError('test-secret'), 'TimeoutError'),
        ):
            with self.subTest(error=expected), patch('ocr.verify.urllib.request.urlopen', side_effect=failure):
                result = read_document(self.image, role='primary', model=PRIMARY_MODEL, api_key='test-secret')
                self.assertEqual(result.error, expected)
                self.assertNotIn('test-secret', result.model_dump_json())

    def test_non_orders_and_multiple_orders_cannot_select_medication_fields(self):
        for kind, count in (('clinical-other', 0), ('prescription', 2), ('unknown', None)):
            with self.subTest(kind=kind, count=count):
                content = reading_fixture()
                content.update(documentType=kind, orderCount=count)
                with self.assertRaises(ValidationError):
                    DocumentReading.model_validate(content)
                for key in FIELD_KEYS[2:]:
                    content['fields'][key].update(value=None, status='missing', sourceText=None)
                self.assertEqual(DocumentReading.model_validate(content).orderCount, count)

    def test_matching_pipeline_releases_with_explicit_checks_and_separate_calls(self):
        requests = []

        def reply(request, timeout):
            payload = json.loads(request.data)
            requests.append(payload)
            return response(payload)

        with patch('ocr.verify.urllib.request.urlopen', side_effect=reply):
            result = run_pipeline(self.image, api_key='test-secret', checks=self.checks())
        self.assertEqual(result.decision.status, 'auto-released')
        self.assertEqual(len(requests), 2)
        self.assertEqual({p['model'] for p in requests}, {PRIMARY_MODEL, VERIFIER_MODEL})
        self.assertTrue(result.signals.independent_verification)

    def test_pipeline_does_not_invent_quality_or_ocr_passes(self):
        with patch('ocr.verify.urllib.request.urlopen', side_effect=lambda req, timeout: response(json.loads(req.data))):
            result = run_pipeline(self.image, api_key='test-secret')
        self.assertEqual(result.decision.status, 'exception')
        self.assertIsNone(result.signals.image_quality_passed)
        self.assertIsNone(result.signals.ocr_checked)
        self.assertIsNone(result.decision.accepted_order)

    def test_conflicting_or_failed_verifier_routes_to_exception(self):
        for fail in (False, True):
            with self.subTest(failed=fail):
                def reply(request, timeout):
                    payload = json.loads(request.data)
                    content = reading_fixture()
                    if payload['model'] == VERIFIER_MODEL:
                        if fail:
                            raise TimeoutError('No response')
                        content['fields']['strength'].update(value='75 mg', sourceText='75 mg')
                    return response(payload, content=content)
                with patch('ocr.verify.urllib.request.urlopen', side_effect=reply):
                    result = run_pipeline(self.image, api_key='test-secret', checks=self.checks())
                self.assertEqual(result.decision.status, 'exception')
                self.assertIsNone(result.decision.accepted_order)

    def test_wrong_image_evidence_and_blank_ocr_reason_fail_before_paid_calls(self):
        for checks in (self.checks().model_copy(update={'input_sha256': '0' * 64}),
                       self.checks().model_copy(update={'ocr_contradictions': {'drug': '  '}})):
            with patch('ocr.verify.urllib.request.urlopen') as network, self.assertRaises(ValueError):
                run_pipeline(self.image, api_key='test-secret', checks=checks)
            network.assert_not_called()

    def test_receipts_cannot_be_written_to_served_project_paths(self):
        self.assertEqual(private_output_path(ROOT / 'artifacts/pipeline/test.json'),
                         ROOT / 'artifacts/pipeline/test.json')
        for path in ('public/test.json', 'dist/test.json', 'src/test.json', 'test.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                private_output_path(ROOT / path)

    def test_stale_or_cross_input_receipts_and_duplicate_calls_cannot_release(self):
        def fresh(image, *, role, model, api_key):
            with patch('ocr.verify.urllib.request.urlopen', side_effect=lambda req, timeout: response(json.loads(req.data))):
                return read_document(image, role=role, model=model, api_key=api_key)

        primary = fresh(self.image, role='primary', model=PRIMARY_MODEL, api_key='test-secret')
        verifier = fresh(self.image, role='verifier', model=VERIFIER_MODEL, api_key='test-secret')
        for changes in ({'input_sha256': '0' * 64}, {'prompt_version': 'stale'},
                        {'prompt_sha256': 'stale'}, {'call_id': primary.call_id},
                        {'role': 'primary'}, {'requested_model': PRIMARY_MODEL}):
            with self.subTest(changes=changes):
                altered = verifier.model_copy(update=changes)
                result = run_pipeline(self.image, api_key='test-secret', checks=self.checks(),
                                      reader=lambda image, role, model, api_key: primary if role == 'primary' else altered)
                self.assertEqual(result.decision.status, 'exception')
                self.assertIsNone(result.decision.accepted_order)
        self.assertEqual(verifier.input_sha256, self.image.sha256)
        shared_primary = primary.model_copy(update={'request_id': 'duplicate-provider-id'})
        shared_verifier = verifier.model_copy(update={'request_id': 'duplicate-provider-id'})
        result = run_pipeline(self.image, api_key='test-secret', checks=self.checks(),
                              reader=lambda image, role, model, api_key:
                              shared_primary if role == 'primary' else shared_verifier)
        self.assertFalse(result.signals.independent_verification)
        self.assertEqual(result.decision.status, 'exception')

    def test_multiple_orders_are_rejected_by_orchestrated_gate(self):
        content = reading_fixture()
        content['orderCount'] = 2
        for key in FIELD_KEYS[2:]:
            content['fields'][key].update(value=None, sourceText=None, status='missing')
        original = copy.deepcopy(content)
        with patch('ocr.verify.urllib.request.urlopen', side_effect=lambda req, timeout:
                   response(json.loads(req.data), content=content)):
            result = run_pipeline(self.image, api_key='test-secret', checks=self.checks())
        self.assertEqual(result.decision.status, 'rejected')
        self.assertEqual(content, original)


if __name__ == '__main__':
    unittest.main()
