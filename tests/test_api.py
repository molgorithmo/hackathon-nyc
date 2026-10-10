import copy
import io
import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from ocr.api import ApiJob, JobError, Jobs, handler
from ocr.pipeline import run_pipeline
from ocr.verify import DocumentReading, ReadingResult, prepare_image, prompt_hash

ROOT = Path(__file__).resolve().parents[1]


class Connection:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, *_):
        return self.input

    def settimeout(self, _):
        pass

    def sendall(self, data):
        self.output.extend(data)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = (ROOT / 'data/clinocr/images/template_8_sample_2_normal.jpg').read_bytes()
        cls.other = (ROOT / 'data/clinocr/images/template_4_sample_2_normal.jpg').read_bytes()
        cls.payload = {**json.loads((ROOT / 'tests/fixtures/release_prescription.json').read_text()), 'orderCount': 1}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.calls = []
        self.directory = Path(self.temporary.name) / 'api'
        self.jobs = Jobs(self.directory, api_key='private-test-key', runner=self.runner)

    def runner(self, image, *, api_key):
        self.calls.append(image.sha256)

        def reader(image, role, model, api_key):
            return ReadingResult(role=role, call_id=role, input_sha256=image.sha256,
                                 prompt_sha256=prompt_hash(role), requested_model=model,
                                 status='ok', finish_reason='stop', latency_seconds=0.1,
                                 raw_response={'private': 'RAW_SENTINEL'},
                                 reading=DocumentReading.model_validate(copy.deepcopy(self.payload)))
        return run_pipeline(image, api_key=api_key, reader=reader)

    def finish(self, jobs=None):
        jobs = jobs or self.jobs
        self.assertTrue(jobs.slot.acquire(timeout=3))
        jobs.slot.release()

    def request(self, method='POST', path='/v1/extractions', data=None, headers=None):
        data = self.data if data is None else data
        values = {'Host': '127.0.0.1:8765', 'X-PillSpark-Request': '1',
                  'Content-Type': 'image/jpeg', 'Content-Length': str(len(data)),
                  'Idempotency-Key': str(uuid.uuid4()), **(headers or {})}
        wire = f'{method} {path} HTTP/1.0\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in values.items()) + '\r\n'
        connection = Connection(wire.encode() + data)
        handler(self.jobs)(connection, ('127.0.0.1', 12345), SimpleNamespace())
        head, body = bytes(connection.output).split(b'\r\n\r\n', 1)
        return int(head.split()[1]), json.loads(body), head

    def test_http_upload_then_get_returns_real_blocking_decision_and_private_receipts(self):
        status, submitted, headers = self.request()
        self.assertEqual(status, 202)
        self.assertEqual(submitted['jobState'], 'processing')
        self.assertIn(b'Cache-Control: no-store', headers)
        self.finish()
        status, job, _ = self.request('GET', '/v1/extractions/' + submitted['extractionId'], b'')
        self.assertEqual(status, 200)
        self.assertEqual(job['jobState'], 'complete')
        self.assertEqual(job['result']['decision']['status'], 'exception')
        self.assertIsNone(job['result']['decision']['accepted_order'])
        self.assertTrue(all(value is None for key, value in job['result']['signals'].items()
                            if key in ('ocr_checked', 'image_quality_passed', 'document_supported', 'in_distribution')))
        self.assertNotIn('RAW_SENTINEL', json.dumps(job))
        self.assertNotIn('private-test-key', json.dumps(job))
        self.assertNotIn('raw_response', json.dumps(job))
        receipt = self.directory / submitted['extractionId'] / 'pipeline.json'
        self.assertIn('RAW_SENTINEL', receipt.read_text())
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(receipt.parent.stat().st_mode & 0o777, 0o700)

    def test_idempotency_survives_restart_and_changed_image_conflicts(self):
        job_id = str(uuid.uuid4())
        self.jobs.submit(job_id, self.data, 'image/jpeg')
        self.finish()
        restored = Jobs(self.directory, api_key='unused', runner=self.runner)
        replay = restored.submit(job_id, self.data, 'image/jpeg')
        self.assertEqual(replay.jobState, 'complete')
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(JobError) as error:
            restored.submit(job_id, self.other, 'image/jpeg')
        self.assertEqual(error.exception.code, 'IDEMPOTENCY_CONFLICT')

    def test_bad_uploads_and_client_gate_bypass_never_call_models(self):
        for data, headers, expected in [
            (b'not an image', {}, 400),
            (self.data[:100], {}, 400),
            (self.data, {'Content-Type': 'image/png'}, 415),
            (b'{"ocr_checked":true,"accepted_order":{}}', {'Content-Type': 'application/json'}, 415),
            (b'x', {'Content-Length': str(10 * 1024 * 1024 + 1)}, 413),
            (b'x', {'Transfer-Encoding': 'chunked'}, 400),
            (b'x', {'Idempotency-Key': '../../outside'}, 400),
            (b'', {}, 413),
        ]:
            with self.subTest(headers=headers):
                status, _, _ = self.request(data=data, headers=headers)
                self.assertEqual(status, expected)
        self.assertEqual(self.calls, [])

    def test_foreign_origin_rebinding_and_missing_request_header_are_blocked(self):
        for headers in ({'Origin': 'https://evil.example'}, {'Host': 'evil.example'},
                        {'X-PillSpark-Request': ''}, {'Origin': 'http://localhost:9999'}):
            status, body, _ = self.request(headers=headers)
            self.assertEqual((status, body['error']), (403, 'LOCAL_REQUEST_REQUIRED'))
        self.assertEqual(self.calls, [])

    def test_missing_key_and_unknown_result_are_actionable(self):
        self.jobs.api_key = ''
        status, body, _ = self.request()
        self.assertEqual((status, body['error']), (503, 'MODEL_KEY_NOT_CONFIGURED'))
        status, body, _ = self.request('GET', '/v1/extractions/' + str(uuid.uuid4()), b'')
        self.assertEqual((status, body['error']), (404, 'JOB_NOT_FOUND'))

    def test_restarted_processing_job_is_failed_without_retry(self):
        job_id = str(uuid.uuid4())
        self.jobs._save(ApiJob(extractionId=job_id, inputHash=prepare_image(self.data).sha256,
                               jobState='processing', receivedAt='test'))
        restored = Jobs(self.directory, api_key='unused', runner=self.runner)
        job = restored.get(job_id)
        self.assertEqual((job.jobState, job.error), ('failed', 'SERVER_RESTARTED'))
        self.assertEqual(self.calls, [])

    def test_worker_failure_does_not_leak_exception_details_or_create_a_decision(self):
        def failed(*args, **kwargs):
            raise RuntimeError('private-test-key patient details')
        self.jobs.runner = failed
        job = self.jobs.submit(str(uuid.uuid4()), self.data, 'image/jpeg')
        self.finish()
        done = self.jobs.get(job.extractionId)
        self.assertEqual((done.jobState, done.error), ('failed', 'PROCESSING_FAILED'))
        self.assertIsNone(done.result)
        self.assertNotIn('private-test-key', done.model_dump_json())

    def test_timeout_is_terminal_and_busy_capacity_is_not_released_early(self):
        unblock = threading.Event()
        self.addCleanup(unblock.set)
        def delayed(image, *, api_key):
            unblock.wait(timeout=3)
            return self.runner(image, api_key=api_key)
        self.jobs.runner, self.jobs.deadline = delayed, 0.03
        job = self.jobs.submit(str(uuid.uuid4()), self.data, 'image/jpeg')
        expires = time.monotonic() + 2
        while self.jobs.get(job.extractionId).jobState == 'processing' and time.monotonic() < expires:
            time.sleep(0.01)
        self.assertEqual(self.jobs.get(job.extractionId).error, 'PROCESSING_TIMEOUT')
        with self.assertRaises(JobError) as error:
            self.jobs.submit(str(uuid.uuid4()), self.data, 'image/jpeg')
        self.assertEqual(error.exception.code, 'PIPELINE_BUSY')
        unblock.set()
        self.finish()
        self.assertIsNone(self.jobs.get(job.extractionId).result)

    def test_non_prescription_rejection_is_preserved(self):
        self.payload = copy.deepcopy(self.payload)
        self.payload.update(documentType='clinical-other', orderCount=0)
        for field in self.payload['fields'].values():
            field.update(value=None, sourceText=None, status='missing', candidates=[])
        job = self.jobs.submit(str(uuid.uuid4()), self.data, 'image/jpeg')
        self.finish()
        done = self.jobs.get(job.extractionId)
        self.assertEqual(done.result.decision.status, 'rejected')
        self.assertIsNone(done.result.decision.accepted_order)

    def test_two_failed_model_reads_become_failed_job(self):
        def failed(image, *, api_key):
            def reader(image, role, model, api_key):
                return ReadingResult(role=role, call_id=role, input_sha256=image.sha256,
                                     prompt_sha256=prompt_hash(role), requested_model=model,
                                     status='error', error='GATEWAY_HTTP_502', latency_seconds=0.1)
            return run_pipeline(image, api_key=api_key, reader=reader)
        self.jobs.runner = failed
        job = self.jobs.submit(str(uuid.uuid4()), self.data, 'image/jpeg')
        self.finish()
        done = self.jobs.get(job.extractionId)
        self.assertEqual((done.jobState, done.error), ('failed', 'MODEL_READINGS_FAILED'))
        self.assertIsNone(done.result)
