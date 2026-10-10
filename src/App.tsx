import { publicAsset } from './publicAsset';
import { useMemo, useState, type FormEvent } from 'react';
import BenchmarkView from './BenchmarkView';
import LiveUploadView from './LiveUploadView';
import {
  FIELD_KEYS,
  FIELD_LABELS,
  isCriticalField,
  type ExtractedField,
  type FieldKey,
  type ReleaseStatus,
  type WorkflowEnvelope,
} from './domain/types';
import {
  DEMO_CASES,
  correctReleasedFieldFixture,
  resolveAmbiguousFixture,
  type DemoCase,
  type ExceptionResolution,
  type FieldCorrection,
} from './services/workflowFixtures';

type View = 'workflow' | 'live upload' | 'summary' | 'benchmark';
type CaseId = DemoCase['id'];
type EnvelopeMap = Record<CaseId, WorkflowEnvelope>;
type ReviewFilter = 'all' | 'needs-review' | 'no-review';

const REVIEW_THRESHOLD = 0.85;

const STATUS_LABELS: Record<ReleaseStatus, string> = {
  'auto-released': 'Automatically released',
  exception: 'Exception',
  rejected: 'Rejected',
};

const createEnvelopeMap = (): EnvelopeMap => Object.fromEntries(
  DEMO_CASES.map((item) => [item.id, item.envelope]),
) as EnvelopeMap;

const ResultBadge = ({ status }: { status: ReleaseStatus }) => (
  <span className={`result-badge result-${status}`}>{STATUS_LABELS[status]}</span>
);

const formatConfidence = (confidence: number) => `${Math.round(confidence * 100)}% confidence`;

const fieldNeedsReview = (field: ExtractedField) =>
  field.status !== 'extracted' || (field.confidence !== null && field.confidence < REVIEW_THRESHOLD);

const reviewCount = (envelope: WorkflowEnvelope) =>
  Object.values(envelope.fields).filter((field) => field && (fieldNeedsReview(field) || envelope.decision?.fieldReasons[field.key]?.length)).length;

const ReviewBadge = ({ envelope }: { envelope: WorkflowEnvelope }) => {
  const count = reviewCount(envelope);
  const rejected = envelope.decision?.status === 'rejected';
  return <span className={`review-badge ${count ? 'review-needed' : 'review-ready'}`}>{count ? `${count} to review` : rejected ? 'No field review' : 'Ready'}</span>;
};

const ReasonList = ({ envelope }: { envelope: WorkflowEnvelope }) => {
  if (!envelope.decision) return null;
  const reasons = [
    ...envelope.decision.documentReasons.map((reason) => ({ ...reason, field: null })),
    ...Object.entries(envelope.decision.fieldReasons).flatMap(([key, fieldReasons]) =>
      (fieldReasons ?? []).map((reason) => ({ ...reason, field: FIELD_LABELS[key as FieldKey] })),
    ),
  ];
  if (!reasons.length) return null;
  const reasonItems = (items: typeof reasons) => <ul>{items.map((reason, index) => (
    <li key={`${reason.code}-${index}`}>
      <code>{reason.code}</code>
      {reason.field && <strong>{reason.field}</strong>}
      <span>{reason.detail}</span>
    </li>
  ))}</ul>;
  return (
    <section className="reason-panel" aria-labelledby="reason-title">
      <h3 id="reason-title">Why this did not release</h3>
      {envelope.decision.status === 'rejected' ? <>
        {reasonItems(reasons.filter(reason => !reason.field))}
        {reasons.some(reason => reason.field) && <details><summary>Field-level reasons</summary>{reasonItems(reasons.filter(reason => reason.field))}</details>}
      </> : reasonItems(reasons)}
    </section>
  );
};

const FieldCorrectionForm = ({ fieldKey, initialValue, onSubmit }: { fieldKey: FieldKey; initialValue: string; onSubmit: (correction: FieldCorrection) => void }) => {
  const [value, setValue] = useState(initialValue);
  const [technician, setTechnician] = useState('Technician 01');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (value.trim() && technician.trim()) onSubmit({ key: fieldKey, value, technician });
  };
  return (
    <form className="field-edit-form" onSubmit={submit}>
      <label>Corrected value<input value={value} onChange={(event) => setValue(event.target.value)} /></label>
      <label>Technician<input value={technician} onChange={(event) => setTechnician(event.target.value)} /></label>
      <button className="primary-button" disabled={!value.trim() || !technician.trim()} type="submit">Send for backend approval</button>
    </form>
  );
};

const FieldList = ({ envelope, onCorrectField }: { envelope: WorkflowEnvelope; onCorrectField?: (correction: FieldCorrection) => void }) => {
  const [editingKey, setEditingKey] = useState<FieldKey | null>(null);
  if (envelope.decision?.status === 'rejected')
    return <p className="empty-order">No order fields or accepted order were created.</p>;
  return (
    <section className="workflow-fields" aria-labelledby="field-title">
      <h3 id="field-title">Structured fields</h3>
      {FIELD_KEYS.map((key) => {
        const field = envelope.fields[key];
        if (!field) return null;
        const needsReview = fieldNeedsReview(field) || Boolean(envelope.decision?.fieldReasons[key]?.length);
        const canEdit = Boolean(onCorrectField && field.value && field.confidence !== null && field.confidence < REVIEW_THRESHOLD);
        return (
          <article className={`workflow-field ${needsReview ? 'field-blocked' : ''}`} key={key}>
            <div className="field-heading">
              <h4>{FIELD_LABELS[key]}</h4>
              {isCriticalField(key) && <span className="critical-label">Critical</span>}
              {needsReview && <span className="field-status field-review">Review</span>}
              {field.confidence !== null
                ? <span className={`field-confidence ${field.confidence < REVIEW_THRESHOLD ? 'confidence-low' : 'confidence-high'}`}>{formatConfidence(field.confidence)}</span>
                : field.status === 'extracted' && <span className="field-confidence confidence-confirmed">{envelope.fixtureEvidence === 'live' ? 'Confidence not calibrated' : 'Technician confirmed'}</span>}
              {canEdit && <button className="edit-field-button" type="button" onClick={() => setEditingKey(editingKey === key ? null : key)}>{editingKey === key ? 'Cancel' : 'Edit'}</button>}
            </div>
            <p className="field-value">{field.value ?? 'Unable to determine'}</p>
            <p className="field-reason">{field.reason}</p>
            <p className="field-evidence-line"><strong>Evidence:</strong> {field.sourceText ?? 'Unavailable'}</p>
            {field.candidates?.length ? (
              <div className="candidate-list" aria-label={`${FIELD_LABELS[key]} candidates`}>
                {field.candidates.map((candidate) => <span key={candidate.id}><strong>{candidate.value}</strong><small>{candidate.confidence === null ? 'Confidence unavailable' : formatConfidence(candidate.confidence)}</small></span>)}
                <small>{envelope.fixtureEvidence === 'live' ? 'Unresolved candidates; no value has been selected.' : 'Select one after clarification, or enter a corrected value below.'}</small>
              </div>
            ) : null}
            {editingKey === key && field.value && onCorrectField && <FieldCorrectionForm fieldKey={key} initialValue={field.value} onSubmit={onCorrectField} />}
          </article>
        );
      })}
    </section>
  );
};

const ExceptionResolutionForm = ({ candidates = [], onSubmit }: { candidates?: ExtractedField['candidates']; onSubmit: (resolution: ExceptionResolution) => void }) => {
  const [resolution, setResolution] = useState<ExceptionResolution>({ dateOfBirth: '', strength: '', refills: '', technician: 'Technician 01' });
  const ready = Object.values(resolution).every((value) => value.trim());
  const submit = (event: FormEvent) => { event.preventDefault(); if (ready) onSubmit(resolution); };
  return (
    <form className="resolution-form" onSubmit={submit}>
      <div className="resolution-heading"><div><p className="eyebrow">Technician exception resolution</p><h3>Clarify the unreadable values</h3></div><span>Revision 1 → 2</span></div>
      <fieldset>
        <legend>Strength after clarification</legend>
        <div className="candidate-actions">
          {candidates.map((candidate) => <button type="button" className={resolution.strength === candidate.value ? 'selected' : ''} onClick={() => setResolution({ ...resolution, strength: candidate.value })} key={candidate.id}><strong>{candidate.value}</strong><small>{candidate.confidence === null ? 'Confidence unavailable' : formatConfidence(candidate.confidence)}</small></button>)}
        </div>
        <label htmlFor="custom-strength">Or enter a corrected strength</label>
        <input id="custom-strength" value={resolution.strength} onChange={(event) => setResolution({ ...resolution, strength: event.target.value })} placeholder="e.g. 37.5 mg" />
      </fieldset>
      <div className="resolution-grid">
        <label>Date of birth after clarification<input value={resolution.dateOfBirth} onChange={(event) => setResolution({ ...resolution, dateOfBirth: event.target.value })} placeholder="MM/DD/YYYY" /></label>
        <label>Refills after clarification<input value={resolution.refills} onChange={(event) => setResolution({ ...resolution, refills: event.target.value })} placeholder="e.g. 0" /></label>
        <label>Technician<input value={resolution.technician} onChange={(event) => setResolution({ ...resolution, technician: event.target.value })} /></label>
      </div>
      <p className="form-note">The technician records corrections; the backend policy remains the release authority.</p>
      <button className="primary-button" disabled={!ready} type="submit">Send for backend approval</button>
    </form>
  );
};

const DecisionPanel = ({ envelope, onResolve, onCorrectField }: { envelope: WorkflowEnvelope; onResolve?: (resolution: ExceptionResolution) => void; onCorrectField?: (correction: FieldCorrection) => void }) => {
  const decision = envelope.decision;
  if (envelope.jobState === 'processing') return <section className="decision-panel"><p role="status">Processing…</p></section>;
  if (envelope.jobState === 'failed' || !decision) return <section className="decision-panel"><p role="alert">Processing failed. No release decision exists.</p></section>;
  const download = decision.acceptedOrder ? `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify({ extractionId: envelope.extractionId, revision: envelope.revision, decision, release: envelope.release }, null, 2))}` : null;
  const assisted = envelope.release?.provenance === 'exception-correction';
  return (
    <section className="decision-panel" aria-labelledby="decision-title">
      <div className="decision-heading"><div><p className="eyebrow">Backend decision</p><h2 id="decision-title">{STATUS_LABELS[decision.status]}</h2></div><ResultBadge status={decision.status} /></div>
      <p className="decision-copy">
        {decision.status === 'auto-released' && (assisted ? 'Technician corrections passed backend revalidation.' : 'Every configured gate passed. No routine field confirmation is required.')}
        {decision.status === 'exception' && 'The backend withheld an accepted order because required evidence is unresolved.'}
        {decision.status === 'rejected' && 'The backend rejected this input and created no accepted order.'}
      </p>
      <dl className="decision-meta">
        <div><dt>Policy</dt><dd>{decision.policyVersion}</dd></div><div><dt>Revision</dt><dd>{envelope.revision}</dd></div><div><dt>Fields to review</dt><dd>{reviewCount(envelope)}</dd></div><div><dt>Accepted order</dt><dd>{decision.acceptedOrder ? 'Created' : 'None'}</dd></div>
      </dl>
      {envelope.release && <p className="release-line">Released by <strong>{envelope.release.actor.id}</strong> · {assisted ? 'technician-assisted' : 'automatic'} · {envelope.release.releasedAt}</p>}
      <ReasonList envelope={envelope} />
      {decision.status === 'exception' && onResolve && <ExceptionResolutionForm candidates={envelope.fields.strength?.candidates} onSubmit={onResolve} />}
      <FieldList envelope={envelope} onCorrectField={onCorrectField} />
      <details className="audit-panel"><summary>Audit history</summary><ol>{envelope.audit.map((event) => <li key={event.id}><strong>{event.type}</strong> · {event.actor}<br />{event.detail}</li>)}</ol></details>
      {download && <a className="primary-action" href={download} download={`${envelope.extractionId}.json`}>Download accepted order JSON</a>}
    </section>
  );
};

const WorkflowView = ({ envelopes, reset, resolve, correctField }: { envelopes: EnvelopeMap; reset: () => void; resolve: (resolution: ExceptionResolution) => void; correctField: (caseId: CaseId, correction: FieldCorrection) => void }) => {
  const [selectedCaseId, setSelectedCaseId] = useState<CaseId>('clear');
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('all');
  const [zoom, setZoom] = useState(100);
  const visibleCases = useMemo(() => DEMO_CASES.filter((item) => {
    if (reviewFilter === 'all') return true;
    const count = reviewCount(envelopes[item.id]);
    return reviewFilter === 'needs-review' ? count > 0 : count === 0;
  }), [reviewFilter, envelopes]);
  const selectedCase = DEMO_CASES.find((item) => item.id === selectedCaseId) ?? DEMO_CASES[0];
  const envelope = envelopes[selectedCase.id];
  const selectCase = (caseId: CaseId) => { setSelectedCaseId(caseId); setZoom(100); };
  const changeFilter = (value: ReviewFilter) => {
    setReviewFilter(value);
    const matches = (item: DemoCase) => value === 'all' || (value === 'needs-review' ? reviewCount(envelopes[item.id]) > 0 : reviewCount(envelopes[item.id]) === 0);
    const next = DEMO_CASES.find(matches);
    const currentVisible = matches(selectedCase);
    if (next && !currentVisible) selectCase(next.id);
  };
  return (
    <main className="workflow-main">
      <section className="workflow-intro"><div><p className="eyebrow">Order Entry Operations</p><h1>Clear the queue without losing the edge cases.</h1></div><p>Review incoming prescriptions, resolve exceptions, and monitor releases from one workspace. Release means downstream order entry, not dispensing authorization.</p></section>
      <div className="workflow-grid">
        <aside className="case-rail" aria-label="Prescription queue">
          <div className="rail-heading"><h2>Prescription queue</h2><button onClick={() => { reset(); selectCase('clear'); setReviewFilter('all'); }}>Reset</button></div>
          <label className="filter-control" htmlFor="review-filter">Field review<select id="review-filter" value={reviewFilter} onChange={(event) => changeFilter(event.target.value as ReviewFilter)}><option value="all">All prescriptions</option><option value="needs-review">Needs review</option><option value="no-review">No field review</option></select></label>
          <p className="filter-note">Calibrated confidence is shown for each extracted value and candidate option.</p>
          {visibleCases.map((item) => <button className={item.id === selectedCase.id ? 'workflow-case selected' : 'workflow-case'} key={item.id} onClick={() => selectCase(item.id)} aria-pressed={item.id === selectedCase.id}><span className="case-topline"><strong>{item.label}</strong><ReviewBadge envelope={envelopes[item.id]} /></span><span>{item.summary}</span></button>)}
          {!visibleCases.length && <p className="empty-filter">No saved cases match this filter.</p>}
        </aside>
        <section className="source-panel" aria-labelledby="source-title">
          <div className="panel-heading"><div><p className="eyebrow">Source document</p><h2 id="source-title">{selectedCase.label}</h2></div><span className={`evidence-label evidence-${envelope.fixtureEvidence}`}>{envelope.fixtureEvidence === 'illustrative' ? 'Evaluation case · not measured model output' : 'Saved measured result'}</span></div>
          <div className="document-controls"><button onClick={() => setZoom(100)}>Fit</button><button onClick={() => setZoom((value) => Math.min(160, value + 15))}>Zoom +</button><button onClick={() => setZoom((value) => Math.max(70, value - 15))}>Zoom −</button><span>{zoom}%</span></div>
          <div className="document-frame"><img src={publicAsset(envelope.source.url)} alt={`${selectedCase.label} source`} style={{ width: `${zoom}%` }} /></div>
          <p className="source-note">{envelope.categorization.label === 'prescription' ? 'Prescription fax' : 'Clinical document'} · page {envelope.source.pageCount}</p>
        </section>
        <DecisionPanel key={`${selectedCase.id}-${envelope.revision}`} envelope={envelope} onResolve={selectedCase.id === 'ambiguous' ? resolve : undefined} onCorrectField={envelope.decision?.status === 'auto-released' ? (correction) => correctField(selectedCase.id, correction) : undefined} />
      </div>
    </main>
  );
};

const SummaryView = ({ envelopes }: { envelopes: EnvelopeMap }) => {
  const rows = DEMO_CASES.map((item) => {
    const envelope = envelopes[item.id];
    const correction = envelope.audit.find((event) => event.type === 'correction');
    const path = envelope.release?.provenance === 'automatic' ? 'Automatic release' : envelope.release?.provenance === 'exception-correction' ? 'Technician-assisted release' : envelope.decision?.status === 'exception' ? 'Awaiting technician' : 'Rejected';
    return { item, envelope, correction, path };
  });
  const automatic = rows.filter((row) => row.envelope.release?.provenance === 'automatic').length;
  const assisted = rows.filter((row) => row.envelope.release?.provenance === 'exception-correction').length;
  const pending = rows.filter((row) => row.envelope.decision?.status === 'exception').length;
  const rejected = rows.filter((row) => row.envelope.decision?.status === 'rejected').length;
  return (
    <main className="summary-main">
      <section className="summary-heading"><p className="eyebrow">Release summary</p><h1>Queue outcomes</h1><p>Saved-case outcomes only. Automatic and technician-assisted releases remain distinct. Live uploads show their own backend result in the Live upload view.</p></section>
      <section className="summary-stats" aria-label="Release totals"><div><strong>{automatic}</strong><span>Automatic releases</span></div><div><strong>{assisted}</strong><span>Technician-assisted</span></div><div><strong>{pending}</strong><span>Awaiting technician</span></div><div><strong>{rejected}</strong><span>Rejected</span></div></section>
      <section className="summary-table-panel"><table className="summary-table"><thead><tr><th>Prescription</th><th>Field review</th><th>Backend result</th><th>Release path</th><th>Technician</th></tr></thead><tbody>{rows.map(({ item, envelope, correction, path }) => <tr key={item.id}><th scope="row">{item.label}<small>{item.summary}</small></th><td><ReviewBadge envelope={envelope} /></td><td>{envelope.decision ? STATUS_LABELS[envelope.decision.status] : envelope.jobState}</td><td>{path}</td><td>{correction?.actor ?? '—'}</td></tr>)}</tbody></table></section>
      <p className="summary-note">Evaluation cases are clearly marked. The non-prescription case is a saved measured rejection. Positive locked-test release metrics remain unavailable.</p>
    </main>
  );
};

export default function App() {
  const [view, setView] = useState<View>('workflow');
  const [envelopes, setEnvelopes] = useState<EnvelopeMap>(createEnvelopeMap);
  const reset = () => setEnvelopes(createEnvelopeMap());
  const resolve = (resolution: ExceptionResolution) => setEnvelopes((current) => ({ ...current, ambiguous: resolveAmbiguousFixture(resolution) }));
  const correctField = (caseId: CaseId, correction: FieldCorrection) => setEnvelopes((current) => ({ ...current, [caseId]: correctReleasedFieldFixture(current[caseId], correction) }));
  return (
    <>
      <header className="site-header" id="top">
        <a className="brand" href="#top" onClick={() => setView('workflow')}><span className="brand-mark" aria-hidden="true" /><span>PillSpark</span><small>Fax to Fill</small></a>
        <span className="demo-label">{import.meta.env.VITE_STATIC_DEMO === "true" ? "Public demo · saved results · no live uploads" : "Order operations"}</span>
        <nav aria-label="Application views">{(['workflow', 'live upload', 'summary', 'benchmark'] as View[]).filter(item => import.meta.env.VITE_STATIC_DEMO !== "true" || item !== "live upload").map((item) => <button key={item} className={view === item ? 'active' : ''} onClick={() => setView(item)} aria-pressed={view === item}>{item[0].toUpperCase() + item.slice(1)}</button>)}</nav>
      </header>
      {view === 'workflow' && <WorkflowView envelopes={envelopes} reset={reset} resolve={resolve} correctField={correctField} />}
      <div hidden={view !== 'live upload'}><LiveUploadView renderDecision={envelope => <DecisionPanel key={`${envelope.extractionId}-${envelope.jobState}`} envelope={envelope} />} /></div>
      {view === 'summary' && <SummaryView envelopes={envelopes} />}
      {view === 'benchmark' && <BenchmarkView />}
    </>
  );
}
