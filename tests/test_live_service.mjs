import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

// Exercise the actual adapter using the existing TypeScript compiler; no test dependency.
const moduleUrl = source => 'data:text/javascript;base64,' + Buffer.from(ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
}).outputText).toString('base64');
const types = moduleUrl(readFileSync(new URL('../src/domain/types.ts', import.meta.url), 'utf8'));
const service = await import(moduleUrl(readFileSync(new URL('../src/services/liveExtractionService.ts', import.meta.url), 'utf8')
  .replace("'../domain/types'", JSON.stringify(types))));
const source = { fileName: 'test.jpg', mimeType: 'image/jpeg', url: 'blob:local-preview', pageCount: 1 };
const field = { value: null, status: 'needs-review', confidence: 0.99, reason: 'Unclear', sourceText: '25 or 75',
  candidates: [{ value: '25 mg', sourceText: '25 or 75' }, { value: '75 mg', sourceText: '25 or 75' }] };
const reading = role => ({ role, model: role, status: 'ok', error: null,
  reading: { documentType: 'prescription', transcription: 'source', fields: { strength: structuredClone(field) } } });
const makeJob = () => ({ extractionId: 'test-id', inputHash: 'a'.repeat(64), jobState: 'complete',
  receivedAt: 'start', completedAt: 'end', error: null,
  result: { primary: reading('primary'), verifier: reading('verifier'), decision: {
    status: 'exception', policy_version: 'ftf-release-v1', document_reasons: [],
    field_reasons: { strength: [{ code: 'AMBIGUOUS_FIELD', source: 'primary', detail: 'Clarify strength' }] },
    accepted_order: null,
  } } });

test('live mapping preserves ambiguity, evidence, reasons and input without claiming calibration', () => {
  const job = makeJob();
  const before = structuredClone(job);
  const result = service.workflowFromJob(job, source);
  assert.equal(result.fields.strength.value, null);
  assert.equal(result.fields.strength.confidence, null);
  assert.equal(result.fields.strength.candidates.length, 2);
  assert.equal(result.fields.strength.candidates[0].confidence, null);
  assert.equal(result.fields.strength.candidates[0].rationale, '25 or 75');
  assert.equal(result.categorization.confidence, null);
  assert.equal(result.fixtureEvidence, 'live');
  assert.equal(result.decision.fieldReasons.strength[0].code, 'AMBIGUOUS_FIELD');
  assert.equal(result.release, null);
  assert.deepEqual(job, before);
});

test('readings are never merged and a failed primary is explicitly identified', () => {
  const job = makeJob();
  job.result.primary.reading.fields.strength = { ...field, value: '25 mg', status: 'extracted', candidates: [] };
  job.result.verifier.reading.fields.strength = { ...field, value: '75 mg', status: 'extracted', candidates: [] };
  assert.equal(service.workflowFromJob(job, source).fields.strength.value, '25 mg');
  job.result.primary.status = 'error'; job.result.primary.reading = null;
  const result = service.workflowFromJob(job, source);
  assert.equal(result.fields.strength.value, '75 mg');
  assert.match(result.categorization.detail, /verifier/);
  assert.equal(result.decision.status, 'exception');
});

test('rejected documents show no order fields or release', () => {
  const job = makeJob(); job.result.decision.status = 'rejected';
  job.result.primary.reading.documentType = 'clinical-other';
  const result = service.workflowFromJob(job, source);
  assert.deepEqual(result.fields, {});
  assert.equal(result.release, null);
  assert.equal(result.categorization.label, 'non-prescription');
});

test('processing and failures never become a completed decision', () => {
  for (const state of ['processing', 'failed']) {
    const job = { ...makeJob(), jobState: state, result: null };
    const result = service.workflowFromJob(job, source);
    assert.equal(result.jobState, state);
    assert.equal(result.decision, null);
    assert.deepEqual(result.fields, {});
    assert.equal(result.categorization.label, 'unknown');
  }
});

test('HTTP response mismatches and incomplete accepted orders are rejected', async () => {
  const previous = globalThis.fetch;
  try {
    for (const change of [job => { job.extractionId = 'another'; },
                         job => { job.result.decision.status = 'auto-released'; job.result.decision.accepted_order = {}; }]) {
      const job = makeJob(); change(job);
      globalThis.fetch = async () => new Response(JSON.stringify(job), { headers: { 'Content-Type': 'application/json' } });
      await assert.rejects(service.requestJob('test-id'), /Invalid/);
    }
  } finally { globalThis.fetch = previous; }
});

test('reopening an existing job makes a GET with no document or model resubmission', async () => {
  const previous = globalThis.fetch;
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, '/v1/extractions/test-id');
      assert.equal(options.method, 'GET');
      assert.equal(options.body, undefined);
      assert.equal(options.headers['X-PillSpark-Request'], '1');
      return new Response(JSON.stringify(makeJob()), { headers: { 'Content-Type': 'application/json' } });
    };
    assert.equal((await service.requestJob('test-id')).jobState, 'complete');
  } finally { globalThis.fetch = previous; }
});
