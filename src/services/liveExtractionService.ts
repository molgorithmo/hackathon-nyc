import { FIELD_KEYS, type ExtractedField, type SourceDocument, type WorkflowEnvelope } from '../domain/types';

interface Reading {
  role: 'primary' | 'verifier';
  model: string;
  status: 'ok' | 'error';
  error: string | null;
  reading: null | {
    documentType: 'prescription' | 'clinical-other' | 'unknown';
    transcription: string;
    fields: Record<string, Omit<ExtractedField, 'key' | 'candidates'> & {
      candidates: { value: string; sourceText: string }[];
    }>;
  };
}

export interface LiveJob {
  extractionId: string;
  inputHash: string;
  jobState: 'processing' | 'complete' | 'failed';
  receivedAt: string;
  completedAt: string | null;
  error: string | null;
  result: null | {
    primary: Reading;
    verifier: Reading;
    decision: {
      status: NonNullable<WorkflowEnvelope['decision']>['status'];
      policy_version: string;
      document_reasons: NonNullable<WorkflowEnvelope['decision']>['documentReasons'];
      field_reasons: NonNullable<WorkflowEnvelope['decision']>['fieldReasons'];
      accepted_order: NonNullable<WorkflowEnvelope['decision']>['acceptedOrder'];
    };
  };
}

const messages: Record<string, string> = {
  MODEL_KEY_NOT_CONFIGURED: 'The local API needs NICRRON_API_KEY in .env.',
  PIPELINE_BUSY: 'Another image is being processed. Try again when that job finishes.',
  INVALID_IMAGE: 'This image cannot be decoded. Choose a single-page JPEG or PNG.',
  IMAGE_TOO_LARGE: 'Choose an image smaller than 10 MiB.',
  UNSUPPORTED_IMAGE_TYPE: 'Only JPEG and PNG images are supported.',
  IMAGE_TYPE_MISMATCH: 'The file contents do not match its image type.',
  MODEL_READINGS_FAILED: 'Neither model returned a complete, valid extraction. No order was released.',
  SERVER_RESTARTED: 'The API restarted during processing. No result was released; calls were not retried.',
  PROCESSING_TIMEOUT: 'Processing exceeded the time limit. No order was released.',
  PROCESSING_FAILED: 'Processing failed. No order was released.',
  IDEMPOTENCY_CONFLICT: 'This request ID already belongs to a different image.',
};

export const errorMessage = (code: string) => messages[code] ?? `Request failed (${code}). No order was released.`;

export async function requestJob(id: string, file?: File, signal?: AbortSignal): Promise<LiveJob> {
  let response: Response;
  try {
    response = await fetch(file ? '/v1/extractions' : `/v1/extractions/${id}`, {
      method: file ? 'POST' : 'GET', body: file,
      headers: { 'X-PillSpark-Request': '1', ...(file ? { 'Content-Type': file.type, 'Idempotency-Key': id } : {}) },
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(20_000)]) : AbortSignal.timeout(20_000),
      cache: 'no-store',
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error('Cannot reach the local extraction API. Start .venv/bin/python -m ocr.api. If a job was submitted, check its result before starting another.');
  }
  if (!response.headers.get('content-type')?.includes('application/json'))
    throw new Error('The extraction API is unavailable. Start .venv/bin/python -m ocr.api.');
  const job = await response.json();
  if (!response.ok) throw new Error(errorMessage(job.error ?? `HTTP_${response.status}`));
  if (job.extractionId !== id || !['processing', 'complete', 'failed'].includes(job.jobState)
      || !/^[a-f0-9]{64}$/.test(job.inputHash)) throw new Error('Invalid extraction response.');
  if (job.jobState === 'complete') {
    const decision = job.result?.decision;
    if (!decision || !['auto-released', 'exception', 'rejected'].includes(decision.status)
        || (decision.status === 'auto-released'
          ? FIELD_KEYS.some(key => typeof decision.accepted_order?.[key] !== 'string' || !decision.accepted_order[key].trim())
          : decision.accepted_order !== null)) throw new Error('Invalid release response.');
  }
  return job;
}

export function workflowFromJob(job: LiveJob, source: SourceDocument): WorkflowEnvelope {
  const result = job.result;
  const chosen = result?.primary.status === 'ok' ? result.primary : result?.verifier.status === 'ok' ? result.verifier : null;
  const reading = chosen?.reading;
  const decision = result?.decision;
  const fields: WorkflowEnvelope['fields'] = {};
  if (reading && decision?.status !== 'rejected') for (const key of FIELD_KEYS) {
    const field = reading.fields[key];
    if (!field) continue;
    fields[key] = { ...field, key, confidence: null,
      candidates: field.candidates.map((candidate, index) => ({ id: `${key}-${index}`,
        value: candidate.value, confidence: null, rationale: candidate.sourceText })) };
  }
  return {
    extractionId: job.extractionId, inputHash: job.inputHash, jobState: job.jobState,
    revision: 1, source,
    categorization: {
      label: reading?.documentType === 'clinical-other' ? 'non-prescription' : reading?.documentType ?? 'unknown',
      confidence: null, basis: 'live-pipeline',
      detail: chosen ? `Fields shown from the ${chosen.role} reading; readings are never merged.` : 'No validated reading available.',
    },
    decision: decision ? { status: decision.status, policyVersion: decision.policy_version,
      documentReasons: decision.document_reasons, fieldReasons: decision.field_reasons,
      acceptedOrder: decision.accepted_order } : null,
    release: decision?.status === 'auto-released' ? { actor: { type: 'policy', id: decision.policy_version },
      policyVersion: decision.policy_version, provenance: 'automatic', revision: 1, releasedAt: job.completedAt! } : null,
    fields, fixtureEvidence: 'live',
    audit: [
      { id: 'received', type: 'received', actor: 'local-api', occurredAt: job.receivedAt, detail: 'Validated original image received.' },
      ...(decision ? [{ id: 'decision', type: decision.status === 'rejected' ? 'rejection' as const : 'decision' as const,
        actor: decision.policy_version, occurredAt: job.completedAt!, detail: `Backend result: ${decision.status}.` }] : []),
    ],
  };
}
