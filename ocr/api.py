"""Loopback-only demo API: validated image -> blind readings -> release gate.

No correction/release endpoint exists in this slice. Unassessed evidence checks
remain blocking. Private job files survive restarts; provider calls never retry.
"""

import argparse
import json
import os
import re
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .pipeline import PipelineResult, private_output_path, run_pipeline
from .prism import PrismTracer
from .regression import save_private
from .release import ReleaseDecision, ReleaseSignals
from .schema import StrictModel
from .verify import DocumentReading, PRIMARY_MODEL, VERIFIER_MODEL, prepare_image

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 10 * 1024 * 1024
JOB_ID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')


def now():
    return datetime.now(timezone.utc).isoformat()


class PublicReading(StrictModel):
    role: Literal['primary', 'verifier']
    model: str
    status: Literal['ok', 'error']
    error: str | None
    reading: DocumentReading | None


class PublicResult(StrictModel):
    primary: PublicReading
    verifier: PublicReading
    signals: ReleaseSignals
    decision: ReleaseDecision


class ApiJob(StrictModel):
    extractionId: str
    inputHash: str
    jobState: Literal['processing', 'complete', 'failed']
    receivedAt: str
    completedAt: str | None = None
    error: str | None = None
    result: PublicResult | None = None


def public_result(result: PipelineResult):
    return PublicResult(decision=result.decision, signals=result.signals, **{
        role: PublicReading(role=role, model=receipt.requested_model, status=receipt.status,
                            error=receipt.error, reading=receipt.reading)
        for role in ('primary', 'verifier') for receipt in (getattr(result, role),)
    })


class JobError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class Jobs:
    def __init__(self, directory, *, api_key, runner=run_pipeline, deadline=150):
        self.directory = private_output_path(Path(directory))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.api_key, self.runner, self.deadline = api_key, runner, deadline
        self.lock, self.slot = threading.RLock(), threading.BoundedSemaphore(1)
        # A restarted server must not reissue paid calls for an interrupted job.
        for path in self.directory.glob('*/job.json'):
            job = ApiJob.model_validate_json(path.read_text())
            if job.jobState == 'processing':
                self._save(job.model_copy(update=dict(jobState='failed', error='SERVER_RESTARTED', completedAt=now())))

    def _path(self, job_id):
        if not JOB_ID.fullmatch(job_id):
            raise JobError(400, 'INVALID_JOB_ID')
        return self.directory / job_id

    def _save(self, job):
        directory = self._path(job.extractionId)
        directory.mkdir(mode=0o700, exist_ok=True)
        # Readers hold the same lock; replace also preserves a valid file after a crash.
        temporary = directory / 'job.tmp'
        save_private(temporary, job.model_dump(mode='json'))
        temporary.replace(directory / 'job.json')

    def get(self, job_id):
        with self.lock:
            path = self._path(job_id) / 'job.json'
            if not path.exists():
                raise JobError(404, 'JOB_NOT_FOUND')
            return ApiJob.model_validate_json(path.read_text())

    def submit(self, job_id, data, mime):
        self._path(job_id)
        try:
            image = prepare_image(data)
        except ValueError:
            raise JobError(400, 'INVALID_IMAGE') from None
        if image.mime_type != mime:
            raise JobError(415, 'IMAGE_TYPE_MISMATCH')
        with self.lock:
            if (self._path(job_id) / 'job.json').exists():
                job = self.get(job_id)
                if job.inputHash != image.sha256:
                    raise JobError(409, 'IDEMPOTENCY_CONFLICT')
                return job
            if not self.api_key:
                raise JobError(503, 'MODEL_KEY_NOT_CONFIGURED')
            if not self.slot.acquire(blocking=False):
                raise JobError(503, 'PIPELINE_BUSY')
            job = ApiJob(extractionId=job_id, inputHash=image.sha256,
                         jobState='processing', receivedAt=now())
            try:
                self._save(job)
                threading.Thread(target=self._process, args=(job, image), daemon=True).start()
            except Exception:
                self.slot.release()
                raise
            return job

    def _fail(self, job_id, code):
        with self.lock:
            job = self.get(job_id)
            if job.jobState == 'processing':
                self._save(job.model_copy(update=dict(jobState='failed', error=code, completedAt=now())))

    def _process(self, job, image):
        timer = threading.Timer(self.deadline, self._fail, args=(job.extractionId, 'PROCESSING_TIMEOUT'))
        timer.daemon = True
        timer.start()
        try:
            result = self.runner(image, api_key=self.api_key)
            with self.lock:
                save_private(self._path(job.extractionId) / 'pipeline.json', result.model_dump(mode='json'), exclusive=True)
                current = self.get(job.extractionId)
                if current.jobState != 'processing':
                    return  # A late result cannot overwrite a timeout with a release.
                if result.primary.status == result.verifier.status == 'error':
                    self._fail(job.extractionId, 'MODEL_READINGS_FAILED')
                else:
                    self._save(current.model_copy(update=dict(jobState='complete', completedAt=now(),
                                                              result=public_result(result))))
        except Exception:
            self._fail(job.extractionId, 'PROCESSING_FAILED')
        finally:
            timer.cancel()
            self.slot.release()


def handler(jobs):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Requests and document content do not belong in ordinary logs.

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self, method):
            try:
                # Block cross-site browser requests and DNS-rebinding hosts. No CORS.
                host = urlsplit('http://' + self.headers.get('Host', ''))
                origin = urlsplit(self.headers.get('Origin', ''))
                if host.hostname not in ('127.0.0.1', 'localhost'):
                    raise JobError(403, 'LOCAL_REQUEST_REQUIRED')
                if origin.geturl() and (origin.scheme != 'http' or origin.hostname not in ('127.0.0.1', 'localhost')
                                       or origin.port not in (5173, 5174, 8765)):
                    raise JobError(403, 'LOCAL_REQUEST_REQUIRED')
                if self.headers.get('X-PillSpark-Request') != '1':
                    raise JobError(403, 'LOCAL_REQUEST_REQUIRED')
                if method == 'GET' and self.path.startswith('/v1/extractions/'):
                    job = jobs.get(self.path.removeprefix('/v1/extractions/'))
                elif method == 'POST' and self.path == '/v1/extractions':
                    if self.headers.get('Transfer-Encoding'):
                        raise JobError(400, 'CONTENT_LENGTH_REQUIRED')
                    lengths = self.headers.get_all('Content-Length', [])
                    if len(lengths) != 1 or not lengths[0].isdigit():
                        raise JobError(400, 'CONTENT_LENGTH_REQUIRED')
                    size = int(lengths[0])
                    if not 0 < size <= MAX_BYTES:
                        raise JobError(413, 'IMAGE_TOO_LARGE')
                    mime = self.headers.get('Content-Type', '')
                    if mime not in ('image/jpeg', 'image/png'):
                        raise JobError(415, 'UNSUPPORTED_IMAGE_TYPE')
                    job_id = self.headers.get('Idempotency-Key', '')
                    jobs._path(job_id)  # Reject invalid IDs before accepting an upload.
                    data = self.rfile.read(size)
                    if len(data) != size:
                        raise JobError(400, 'INCOMPLETE_UPLOAD')
                    job = jobs.submit(job_id, data, mime)
                else:
                    raise JobError(404, 'NOT_FOUND')
                self.reply(202 if job.jobState == 'processing' else 200, job.model_dump(mode='json'))
            except JobError as exc:
                self.reply(exc.status, dict(error=exc.code))
            except (TimeoutError, socket.timeout):
                self.reply(408, dict(error='UPLOAD_TIMEOUT'))
            except Exception:
                self.reply(500, dict(error='INTERNAL_ERROR'))

        def do_POST(self):
            self.dispatch('POST')

        def do_GET(self):
            self.dispatch('GET')

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    config = {**dotenv_values(ROOT / '.env'), **os.environ}
    # This slice pins the same models/prompts used by the existing blind pipeline.
    tracer = PrismTracer.from_values(config)
    jobs = Jobs(ROOT / 'artifacts/api', api_key=config.get('NICRRON_API_KEY', ''),
                runner=lambda image, *, api_key: run_pipeline(image, api_key=api_key, tracer=tracer))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(jobs))
    print(f'Local extraction API: http://127.0.0.1:{args.port} ({PRIMARY_MODEL}, {VERIFIER_MODEL})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
