import io
import json
import unittest
from pathlib import Path

from ocr.pipeline import run_pipeline
from ocr.prism import PrismConfig, PrismTracer
from ocr.verify import DocumentReading, ReadingResult, prepare_image, prompt_hash


ROOT = Path(__file__).resolve().parents[1]


def reading_fixture():
    return json.loads((ROOT / 'tests/fixtures/release_prescription.json').read_text())


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PrismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = prepare_image((ROOT / 'data/clinocr/images/template_8_sample_2_normal.jpg').read_bytes())

    def result(self, tracer):
        payload = reading_fixture()
        payload['orderCount'] = 1
        payload['fields']['patientName'].update(value='PRIVATE PATIENT', sourceText='PRIVATE PATIENT')

        def reader(image, role, model, api_key):
            return ReadingResult(role=role, call_id=role, input_sha256=image.sha256,
                                 prompt_sha256=prompt_hash(role), requested_model=model,
                                 returned_model=model, status='ok', finish_reason='stop',
                                 latency_seconds=.25, usage={'prompt_tokens': 10, 'completion_tokens': 5},
                                 raw_response={'secret': 'RAW PRIVATE PATIENT'},
                                 reading=DocumentReading.model_validate(payload))
        return run_pipeline(self.image, api_key='NICRRON SECRET', reader=reader, tracer=tracer)

    def test_trace_groups_readings_and_excludes_source_content_and_secrets(self):
        requests = []

        def open_(request, timeout):
            self.assertEqual(timeout, 8)
            requests.append(request)
            return Response(b'{"id":"stored"}')

        tracer = PrismTracer(PrismConfig('PRISM SECRET', 'project-id', 'https://prism.example'), opener=open_)
        result = self.result(tracer)
        self.assertEqual(result.decision.status, 'exception')
        self.assertEqual(len(requests), 2)
        bodies = [json.loads(request.data) for request in requests]
        self.assertEqual(len({body['session_id'] for body in bodies}), 1)
        self.assertEqual({body['agent_name'] for body in bodies}, {'PillSpark Fax to Fill'})
        self.assertEqual({body['metadata']['role'] for body in bodies}, {'primary', 'verifier'})
        self.assertTrue(all(body['metadata']['phi_redacted'] for body in bodies))
        self.assertTrue(all(body['token_count_input'] == 10 for body in bodies))
        public = json.dumps(bodies)
        for private in ('PRIVATE PATIENT', 'RAW PRIVATE PATIENT', 'NICRRON SECRET', 'PRISM SECRET', self.image.sha256):
            self.assertNotIn(private, public)
        self.assertNotIn('image_url', public)
        self.assertTrue(all(request.headers['X-prismtrace-key'] == 'PRISM SECRET' for request in requests))

    def test_missing_or_partial_config_is_explicit(self):
        self.assertIsNone(PrismConfig.from_values({}))
        with self.assertRaises(ValueError):
            PrismConfig.from_values({'PRISMTRACE_API_KEY': 'x'})
        with self.assertRaises(ValueError):
            PrismConfig.from_values({'PRISMTRACE_API_KEY': 'x', 'PRISMTRACE_PROJECT_ID': 'p',
                                     'PRISMTRACE_HOST': 'http://not-secure.example'})

    def test_prism_failure_never_changes_release_decision(self):
        tracer = PrismTracer(PrismConfig('key', 'project', 'https://prism.example'),
                             opener=lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError('down')))
        result = self.result(tracer)
        self.assertEqual(result.decision.status, 'exception')
        self.assertIsNone(result.decision.accepted_order)


if __name__ == '__main__':
    unittest.main()
