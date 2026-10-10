"""PHI-safe PRISM tracing for validated pipeline outcomes."""

import json
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

from .schema import FIELD_KEYS


@dataclass(frozen=True)
class PrismConfig:
    api_key: str
    project_id: str
    host: str

    @classmethod
    def from_values(cls, values):
        names = ('PRISMTRACE_API_KEY', 'PRISMTRACE_PROJECT_ID', 'PRISMTRACE_HOST')
        found = {name: (values.get(name) or '').strip() for name in names}
        if not any(found.values()):
            return None
        if not all(found.values()):
            raise ValueError('Set all PRISMTRACE_API_KEY, PRISMTRACE_PROJECT_ID, and PRISMTRACE_HOST values')
        parsed = urlsplit(found['PRISMTRACE_HOST'])
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.path.rstrip('/')
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('PRISMTRACE_HOST must be an HTTPS origin without a path')
        return cls(api_key=found['PRISMTRACE_API_KEY'], project_id=found['PRISMTRACE_PROJECT_ID'],
                   host=found['PRISMTRACE_HOST'].rstrip('/'))


class PrismTracer:
    """Send operational summaries only; never images, transcriptions, or field values."""

    def __init__(self, config: PrismConfig, *, opener=urllib.request.urlopen):
        self.config, self.opener = config, opener

    @classmethod
    def from_values(cls, values):
        config = PrismConfig.from_values(values)
        return cls(config) if config else None

    def _trace(self, image, result, receipt, session_id):
        reading = receipt.reading
        counts = {status: 0 for status in ('extracted', 'needs-review', 'missing')}
        if reading:
            for key in FIELD_KEYS:
                counts[getattr(reading.fields, key).status] += 1
        reasons = sorted({reason.code for reason in result.decision.document_reasons} | {
            reason.code for items in result.decision.field_reasons.values() for reason in items})
        input_summary = {
            'role': receipt.role, 'prompt_version': receipt.prompt_version,
            'image': {'mime_type': image.mime_type, 'width': image.width, 'height': image.height},
            'source_content': 'redacted',
        }
        output_summary = {
            'status': receipt.status, 'error': receipt.error,
            'document_type': reading.documentType if reading else None,
            'order_count': reading.orderCount if reading else None,
            'field_status_counts': counts, 'release_status': result.decision.status,
            'release_reason_codes': reasons,
        }
        usage = receipt.usage or {}
        tokens = lambda name: usage[name] if type(usage.get(name)) is int and usage[name] >= 0 else 0
        payload = {
            'project_id': self.config.project_id,
            'model': receipt.requested_model,
            'input_messages': [{'role': 'user', 'content': json.dumps(input_summary, sort_keys=True)}],
            'output_message': json.dumps(output_summary, sort_keys=True),
            'latency_ms': round(receipt.latency_seconds * 1000),
            'token_count_input': tokens('prompt_tokens'),
            'token_count_output': tokens('completion_tokens'),
            'session_id': session_id,
            'trace_id': f'ftf-{receipt.call_id}',
            'agent_id': 'pillspark-fax-to-fill',
            'agent_name': 'PillSpark Fax to Fill',
            'metadata': {
                'role': receipt.role, 'prompt_version': receipt.prompt_version,
                'release_policy_version': result.decision.policy_version,
                'release_status': result.decision.status,
                'source_content_included': False, 'phi_redacted': True,
            },
        }
        request = urllib.request.Request(
            self.config.host + '/api/traces', data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'X-PRISMtrace-Key': self.config.api_key},
            method='POST')
        with self.opener(request, timeout=8) as response:
            if getattr(response, 'status', 200) >= 300:
                raise urllib.error.HTTPError(request.full_url, response.status, 'PRISM ingest failed', {}, None)
            return json.load(response)

    def emit_pipeline(self, image, result):
        session_id = 'ftf-run-' + str(uuid.uuid4())
        # The API pipeline already runs off the upload request thread; emit both calls concurrently.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self._trace, image, result, receipt, session_id)
                       for receipt in (result.primary, result.verifier)]
            return [future.result() for future in futures]

