import { publicAsset } from './publicAsset';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { SourceDocument, WorkflowEnvelope } from './domain/types';
import { errorMessage, requestJob, workflowFromJob, type LiveJob } from './services/liveExtractionService';

export default function LiveUploadView({ renderDecision }: { renderDecision: (envelope: WorkflowEnvelope) => ReactNode }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [job, setJob] = useState<LiveJob | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const choose = (value: File | null) => {
    controller.current?.abort();
    setJob(null); setRequestId(null); setError('');
    if (value && (!['image/jpeg', 'image/png'].includes(value.type) || value.size > 10 * 1024 * 1024)) {
      setFile(null); setPreview(''); setError('Choose one JPEG or PNG, up to 10 MiB. PDFs are not supported yet.'); return;
    }
    setFile(value);
    setPreview(value ? URL.createObjectURL(value) : '');
  };

  const loadExample = async () => {
    setBusy(true); setError('');
    try {
      const response = await fetch(publicAsset('/run/template_8_sample_2_normal.jpg'));
      if (!response.ok || !response.headers.get('content-type')?.includes('image/jpeg'))
        throw new Error('Gathered example unavailable. Export the viewer assets or choose a local image.');
      choose(new File([await response.blob()], 'clinocr-example.jpg', { type: 'image/jpeg' }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Example unavailable.');
    } finally { setBusy(false); }
  };

  const run = async (resume = false) => {
    if (!file || busy) return;
    const id = resume ? requestId : crypto.randomUUID();
    if (!id) return;
    const active = new AbortController();
    controller.current = active;
    setBusy(true); setError(''); setRequestId(id);
    if (!resume) setJob(null);
    try {
      const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
      const inputHash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
      let next = await requestJob(id, resume ? undefined : file, active.signal);
      if (next.inputHash !== inputHash) throw new Error('The backend result belongs to a different image.');
      setJob(next);
      const deadline = Date.now() + 165_000;
      while (next.jobState === 'processing') {
        if (Date.now() > deadline) throw new Error('Still awaiting the API. Use Check existing result; the image will not be submitted again.');
        await new Promise<void>(resolve => setTimeout(resolve, 1200));
        active.signal.throwIfAborted();
        next = await requestJob(id, undefined, active.signal);
        if (next.inputHash !== inputHash) throw new Error('The backend result belongs to a different image.');
        setJob(next);
      }
      if (next.jobState === 'failed') setError(errorMessage(next.error ?? 'PROCESSING_FAILED'));
    } catch (failure) {
      if (!active.signal.aborted) setError(failure instanceof Error ? failure.message : 'Extraction failed.');
    } finally {
      if (controller.current === active) setBusy(false);
    }
  };

  const source: SourceDocument = { fileName: file?.name ?? '', mimeType: file?.type ?? '', url: preview, pageCount: 1 };
  const envelope = job ? workflowFromJob(job, source) : null;
  return (
    <main className="workflow-main">
      <section className="workflow-intro"><div><p className="eyebrow">Live extraction</p><h1>Read an image through the real pipeline.</h1></div><p>Two independent Nicrron readings and the backend release policy. This is a local prototype; release means downstream order entry.</p></section>
      <section className="live-upload-controls">
        <label htmlFor="prescription-image">Prescription image (JPEG or PNG, up to 10 MiB)<input id="prescription-image" type="file" accept="image/jpeg,image/png" disabled={busy} onChange={event => choose(event.target.files?.[0] ?? null)} /></label>
        <button className="primary-button" type="button" disabled={!file || busy || Boolean(requestId)} onClick={() => void run()}>Extract image</button>
        <button type="button" disabled={busy} onClick={() => void loadExample()}>Use gathered ClinOCR example</button>
        {requestId && <button type="button" disabled={busy} onClick={() => void run(true)}>Check existing result</button>}
        <p>Unassessed OCR, quality, support, and distribution checks block automatic release. Live corrections are not connected yet.</p>
        <p>The gathered example is a synthetic clinical note, useful for checking rejection—not prescription accuracy. Each extraction sends the selected image to Nicrron.</p>
        {busy && <p role="status">Processing original image… No order has been accepted.</p>}
        {error && <p role="alert" className="live-error">{error}</p>}
        {requestId && <p className="live-job-id">Job: {requestId}</p>}
      </section>
      {preview && <div className="live-upload-grid">
        <section className="source-panel"><div className="panel-heading"><h2>Uploaded source</h2><span className="evidence-label">Original image</span></div><div className="document-frame"><img src={preview} alt="Uploaded prescription source" /></div></section>
        <div>
          {envelope ? renderDecision(envelope) : <section className="decision-panel"><p>Select Extract image to request the backend decision.</p></section>}
          {job?.result && <section className="decision-panel live-readings"><h3>Independent readings</h3><p>{envelope?.categorization.detail} Scores are uncalibrated and do not approve a release.</p>
            {([job.result.primary, job.result.verifier]).map(reading => <details key={reading.role}><summary>{reading.role} · {reading.model} · {reading.status}{reading.error ? ` · ${reading.error}` : ''}</summary>{reading.reading && <><p>Document: {reading.reading.documentType}</p><pre>{reading.reading.transcription}</pre><dl>{Object.entries(reading.reading.fields).map(([key, field]) => <div key={key}><dt>{key}</dt><dd>{field.value ?? 'Unable to determine'}<small>Evidence: {field.sourceText ?? 'Unavailable'}</small>{field.candidates.map((candidate, index) => <small key={index}>Candidate: {candidate.value} · {candidate.sourceText}</small>)}</dd></div>)}</dl></>}</details>)}
          </section>}
        </div>
      </div>}
    </main>
  );
}
