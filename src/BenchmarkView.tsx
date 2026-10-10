import { publicAsset } from './publicAsset';
import React, { useEffect, useState, useCallback } from "react";
import { FIELD_LABELS, type FieldKey } from "./domain/types";
import WordBenchmark, { type WordReport } from './WordBenchmark';
type CaseScore = {
  case_id: string;
  cer: number;
  subset: string;
};
type Token = {
  text: string;
  confidence: number;
  polygon: number[][];
  source_polygon: number[][];
};
type OCR = {
  status: string;
  transcription: string;
  tokens: Token[];
};
type Field = {
  value: string | null;
  status: string;
  sourceText: string | null;
  confidence: number | null;
  candidates: {
    value: string;
    sourceText: string;
  }[];
  reason: string;
};
type CaseResult = {
  id: string;
  subset: string;
  originalImage: string;
  enhancedImage: string | null;
  imageWidth: number;
  imageHeight: number;
  enhancedWidth: number | null;
  enhancedHeight: number | null;
  reference: string;
  vision: {
    status: string;
    error: string | null;
    latencySeconds: number | null;
    documentType: string | null;
    transcription: string;
    notes: string[];
    fields: Record<string, Field> | null;
  };
  paddleOriginal: OCR | null;
  paddleEnhanced: OCR | null;
};
type TextScore = {
  character_error_rate: number;
  cases: CaseScore[];
};
type VisionMetrics = {
  model: string;
  accepted_outputs: number;
  failed_or_rejected_outputs: number;
  median_request_seconds: number;
  estimated_cost_usd: number | null;
  text: TextScore;
};
type Metrics = {
  cases: number;
  positive_prescription_cases: number;
  vision: VisionMetrics;
  paddle_original: {
    text: TextScore;
  };
  paddle_enhanced: {
    text: TextScore;
  };
  enhancement_comparison: {
    improved: number;
    worsened: number;
  };
};
type Data = {
  generatedAt: string;
  metrics: Metrics;
  cases: CaseResult[];
  words?: WordReport;
  regression?: {
    policy_version: string;
    expected_cases: number;
    recorded_cases: number;
    non_prescription_blocked: number;
    decisions: Record<string, number>;
    model_reads: Record<string, {
      model: string;
      schema_valid: number;
      recorded: number;
      reported_prompt_tokens: number;
      reported_completion_tokens: number;
      usage_records: number;
    }>;
    processing_latency: {
      measured_cases: number;
      p50_seconds: number | null;
      p95_seconds: number | null;
    };
    cases: {
      id: string;
      status: string;
      reason_codes?: string[];
      primary_status?: string;
      primary_error?: string | null;
      verifier_status?: string;
      verifier_error?: string | null;
    }[];
  };
};
type SubsetFilter = string;
type ValidationFilter = "all" | "accepted" | "rejected";
const CERBar = ({ label, value }: {
  label: string;
  value: number | null;
}) => {
  const pct = value === null ? 0 : Math.min(1, value) * 100;
  return (<div className="cerbar" aria-label={`${label} CER ${value === null ? "unavailable" : (value * 100).toFixed(1) + "%"}`}>
    <div className="cerbar-label">{label}</div>
    <div className="cerbar-track">
      <div className="cerbar-bar" style={{ width: `${pct}%` }} />
    </div>
    <div className="cerbar-value">{value === null ? "N/A" : (value * 100).toFixed(1) + "%"}</div>
  </div>);
};
const Badge = ({ children, color }: {
  children: React.ReactNode;
  color: string;
}) => <span className={`badge badge-${color}`}>{children}</span>;
const TabButton = ({ id, label, selected, onClick }: {
  id: string;
  label: string;
  selected: boolean;
  onClick: () => void;
}) => <button role="tab" aria-selected={selected} aria-controls={`${id}-panel`} id={`${id}-tab`} tabIndex={0} onClick={onClick} className={selected ? "tab-button tab-selected" : "tab-button"}>{label}</button>;
const FieldRow = ({ name: key, field }: {
  name: string;
  field: Field;
}) => {
  const [expanded, setExpanded] = useState(false);
  return <>
    <tr>
      <th scope="row">{FIELD_LABELS[key as FieldKey] ?? key}</th>
      <td>{field.value ?? '(missing)'}</td>
      <td>{field.status}</td>
      <td>
        <button aria-expanded={expanded} aria-controls={`${key}-details`} onClick={() => setExpanded(!expanded)} className="small-button">Details</button>
      </td>
    </tr>
    <tr hidden={!expanded} id={`${key}-details`}>
      <td colSpan={4} className="field-evidence">
        <p>
          <b>Evidence:</b> {field.sourceText ?? 'Unavailable'}</p>
        <p>
          <b>Score:</b> {field.confidence === null ? 'Not supplied' : `${(field.confidence * 100).toFixed(1)}% (uncalibrated)`}</p>
        <p>
          <b>Reason:</b> {field.reason || '(none)'}</p>
        {field.candidates.length > 0 && <>
          <b>Candidates:</b>
          <ul>{field.candidates.map((c, i) => <li key={i}>{c.value} ({c.sourceText})</li>)}</ul>
        </>}
      </td>
    </tr>
  </>;
};
const BenchmarkView: React.FC = () => {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [subsetFilter, setSubsetFilter] = useState<SubsetFilter>("all");
  const [validationFilter, setValidationFilter] = useState<ValidationFilter>("all");
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [showEnhanced, setShowEnhanced] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [showOverlay, setShowOverlay] = useState(false);
  const [transTab, setTransTab] = useState<"nicrron" | "paddleOriginal" | "paddleEnhanced" | "reference">("nicrron");
  const fetchData = useCallback(() => {
    const ac = new AbortController(); fetch(publicAsset("/run/results.json"), { cache: "no-store", signal: ac.signal }).then(async (res) => {
      if(!res.ok)
        throw new Error(`HTTP ${res.status}`);
      const json: Data = await res.json(); setData(json); setLoading(false);
      if(json.cases.length > 0) {
        const firstRejected = json.cases.find(c => c.vision.status.toLowerCase() === "error");
        setSelectedCaseId(firstRejected?.id ?? json.cases[0].id);
      }
      else
        setSelectedCaseId(null);
    }).catch(e => {
      if(e.name !== "AbortError") {
        setError(e.message);
        setLoading(false);
      }
    });
    return () => ac.abort();
  }, []);
  useEffect(() => {
    const cleanup = fetchData();
    return () => { cleanup(); };
  }, [fetchData]);
  if(loading)
    return (<main>
      <header>
        <h1>Fax to Fill <span className="subtitle">OCR experiment</span> <button onClick={() => { setLoading(true); setError(null); fetchData(); }} disabled={loading} aria-label="Refresh report">Refresh snapshot</button>
        </h1>
      </header>
      <p role="status">Loading report…</p>
      <footer>run .venv/bin/python -m ocr.export_viewer after new OCR runs to update snapshot.</footer>
    </main>);
  if(error)
    return (<main>
      <header>
        <h1>Fax to Fill <span className="subtitle">OCR experiment</span> <button onClick={() => { setLoading(true); setError(null); fetchData(); }} disabled={loading} aria-label="Retry loading report">Refresh snapshot</button>
        </h1>
      </header>
      <p role="alert">Error loading report: {error}</p>
      <footer>run .venv/bin/python -m ocr.export_viewer after new OCR runs to update snapshot.</footer>
    </main>);
  if(!data)
    return null;
  const { metrics, cases, generatedAt } = data;
  const regression = data.regression;
  const subsets = Array.from(new Set(cases.map(c => c.subset))).sort();
  const filteredCases = cases.filter(c => (subsetFilter === "all" || c.subset === subsetFilter) && (validationFilter === "all" || ((validationFilter === "accepted" && c.vision.status.toLowerCase() === "ok") || (validationFilter === "rejected" && c.vision.status.toLowerCase() === "error"))));
  const selectedCase = filteredCases.find(c => c.id === selectedCaseId) || filteredCases[0] || null;
  const cerVision = metrics.vision.text.character_error_rate;
  const cerPaddleOrig = metrics.paddle_original.text.character_error_rate;
  const cerPaddleEnh = metrics.paddle_enhanced.text.character_error_rate;
  const acceptedCount = metrics.vision.accepted_outputs;
  const rejectedCount = metrics.vision.failed_or_rejected_outputs;
  const totalCost = metrics.vision.estimated_cost_usd;
  const isRejected = selectedCase?.vision.status.toLowerCase() === "error";
  const zoomPct = Math.min(200, Math.max(50, zoom));
  const imgWidth = showEnhanced ? (selectedCase?.enhancedWidth ?? selectedCase?.imageWidth ?? 0) : (selectedCase?.imageWidth ?? 0);
  const imgHeight = showEnhanced ? (selectedCase?.enhancedHeight ?? selectedCase?.imageHeight ?? 0) : (selectedCase?.imageHeight ?? 0);
  const imgSrc = showEnhanced ? (selectedCase?.enhancedImage ?? selectedCase?.originalImage) : selectedCase?.originalImage || "";
  const overlayTokens = (showEnhanced ? selectedCase?.paddleEnhanced?.tokens : selectedCase?.paddleOriginal?.tokens) || [];
  const overlayPolygons = overlayTokens.map((t, i) => <polygon key={i} points={(showEnhanced ? t.polygon : t.source_polygon).map(p => p.join(",")).join(" ")} aria-label={`${t.text} uncalibrated score ${(t.confidence * 100).toFixed(0)}%`} tabIndex={0}>
    <title>{`${t.text} uncalibrated score ${(t.confidence * 100).toFixed(0)}%`}</title>
  </polygon>);
  const transcriptionText = () => {
    switch(transTab) {
      case "nicrron": return selectedCase?.vision.transcription || "";
      case "paddleOriginal": return selectedCase?.paddleOriginal?.transcription || "";
      case "paddleEnhanced": return selectedCase?.paddleEnhanced?.transcription || "";
      case "reference": return selectedCase?.reference || "";
      default: return "";
    }
  };
  return (<main>
    <header>
      <h1>Fax to Fill <span className="subtitle">OCR experiment</span> <button onClick={() => { setLoading(true); setError(null); fetchData(); }} disabled={loading} aria-label="Refresh report">Refresh snapshot</button>
      </h1>
    </header>
    <p className="caveat">{data.words ? 'Synthetic ClinOCR pages and RxHandBD word crops; no complete prescription-order accuracy measurement.' : 'Synthetic clinical documents only; no prescription orders; not prescription accuracy.'}</p>
    <p className="generated">Report generated at {generatedAt}, model: {metrics.vision.model}</p>
    {data.words && <WordBenchmark report={data.words} />}
    <section className="locked-metrics" aria-label="Locked test release metrics">
      <div className="locked-heading">
        <div>
          <p className="eyebrow">Locked-test release metrics</p>
          <h2>Positive prescription evidence is not available</h2>
        </div>
        <Badge color="amber">0 positive cases</Badge>
      </div>
      <div className="metric-grid">
        {[
          ['Whole-order accuracy', 'Unavailable'],
          ['Critical false accepts', 'Unavailable'],
          ['Straight-through coverage', 'Unavailable'],
          ['Exception recall', 'Unavailable'],
          ['Confidence bounds', 'Unavailable'],
          ['Selective-risk curve', 'Unavailable'],
        ].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
      </div>
      <p className="explain">No locked positive prescription set exists yet. ClinOCR character error rate and evaluation workflow cases are not substitutes for release accuracy.</p>
    </section>
    {regression && <section aria-label="Blind pipeline regression">
      <h2>Blind pipeline · {regression.recorded_cases}/{regression.expected_cases} gathered documents</h2>
      <p>Blocked from order entry: <Badge color="teal">{regression.non_prescription_blocked}/{regression.expected_cases}</Badge>{" "}
        Automatically released: {regression.decisions["auto-released"]} · Exceptions: {regression.decisions.exception} · Rejected: {regression.decisions.rejected}</p>
      <p className="explain">Policy {regression.policy_version}. This set contains zero prescription orders. Unknown OCR, quality, and support checks block release; these results do not establish prescription accuracy or release coverage.</p>
      {Object.entries(regression.model_reads).map(([role, reading]) => <p key={role}>
        {role}: {reading.model} · Schema-valid reads: {reading.schema_valid}/{reading.recorded} · Reported tokens: {reading.reported_prompt_tokens.toLocaleString()} input / {reading.reported_completion_tokens.toLocaleString()} output ({reading.usage_records}/{reading.recorded} usage receipts)
      </p>)}
      <p>Processing latency: median {regression.processing_latency.p50_seconds?.toFixed(2) ?? "N/A"}s · P95 {regression.processing_latency.p95_seconds?.toFixed(2) ?? "N/A"}s · {regression.processing_latency.measured_cases} measured cases. Billed cost: unknown. Prescription accuracy / release coverage: N/A.</p>
      <details>
        <summary>Inspect decisions and failure reasons</summary>
        <table>
          <thead><tr><th>Document</th><th>Decision</th><th>Primary / verifier</th><th>Reasons</th></tr></thead>
          <tbody>{regression.cases.map(row => <tr key={row.id}>
            <th scope="row">{row.id}</th><td>{row.status}</td>
            <td>{row.primary_error ?? row.primary_status ?? "unprocessed"} / {row.verifier_error ?? row.verifier_status ?? "unprocessed"}</td>
            <td>{row.reason_codes?.join(", ") ?? "Not processed"}</td>
          </tr>)}</tbody>
        </table>
      </details>
    </section>}
    <section aria-label="Summary character error rates">
      <h2>Reading error rate across {metrics.cases} documents</h2>
      <CERBar label="Vision raw" value={cerVision} />
      <CERBar label="Paddle original" value={cerPaddleOrig} />
      <CERBar label="Paddle enhanced" value={cerPaddleEnh} />
      <p className="explain">Source: saved ClinOCR baseline · Character error rate (%) · Casefolded text, whitespace collapsed. Lower CER better; reading order and digits significant; not field accuracy.</p>
      <p>Schema accepted (unreviewed): <Badge color="teal">{acceptedCount}</Badge> Rejected / failed: <Badge color="amber">{rejectedCount}</Badge> Estimated model cost (not billed): {totalCost === null ? "N/A" : `$${totalCost.toFixed(4)}`}</p>
    </section>
    <section aria-label="Case filters">
      <label htmlFor="subset-select">Subset:</label>
      <select id="subset-select" value={subsetFilter} onChange={e => setSubsetFilter(e.target.value)}>
        <option value="all">All</option>{subsets.map(s => <option key={s} value={s}>{s}</option>)}</select>
      <label htmlFor="validation-select">Validation:</label>
      <select id="validation-select" value={validationFilter} onChange={e => setValidationFilter(e.target.value as ValidationFilter)}>
        <option value="all">All</option>
        <option value="accepted">Accepted</option>
        <option value="rejected">Rejected</option>
      </select>
    </section>
    <section className="container">
      <aside aria-label="Cases list">
        <ul>{filteredCases.map(c => {
          const cerVis = metrics.vision.text.cases.find(cs => cs.case_id === c.id)?.cer ?? null;
          return (<li key={c.id}>
            <button className={c.id === selectedCase?.id ? "case-button selected" : "case-button"} onClick={() => { setSelectedCaseId(c.id); setShowEnhanced(false); setZoom(100); setShowOverlay(false); setTransTab("nicrron"); }} aria-pressed={c.id === selectedCase?.id} aria-label={`Select case ${c.id}`}>{c.id.replace(/^template_(\d+)_sample_(\d+)_.*$/, "Template $1 · Sample $2")}<small>{c.subset} · {c.vision.status === "ok" ? "Schema accepted" : "Rejected"}</small> <span className="mini-cer">CER: {cerVis === null ? "N/A" : (cerVis * 100).toFixed(1) + "%"}</span>
            </button>
          </li>);
        })}</ul>
      </aside>
      <article aria-label="Selected case details" className="case-view">{selectedCase ? <>{isRejected && <div className="banner amber" role="alert">Raw model suggestions failed validation; unsafe for orders; showing raw fields only.</div>}<section className="image-panel">
        <div className="image-controls">
          <label>
            <input type="checkbox" checked={showEnhanced} disabled={!selectedCase.enhancedImage} onChange={e => setShowEnhanced(e.target.checked)} /> Enhanced image</label>
          <label>
            <input type="checkbox" checked={showOverlay} onChange={e => setShowOverlay(e.target.checked)} disabled={!overlayTokens.length} /> Show OCR overlay</label>
          <label>Zoom <input type="range" min={50} max={200} value={zoomPct} onChange={e => setZoom(Number(e.target.value))} /> {zoomPct}%</label>
        </div>
        <div className="image-scroll">
          <div className="image-container" style={{ width: `${zoomPct}%` }}>
            <img src={publicAsset(imgSrc ?? "")} alt={`Case ${selectedCase.id} ${showEnhanced ? "enhanced" : "original"} image`} width={imgWidth} height={imgHeight} style={{ display: "block", width: "100%", height: "auto" }} />
            <svg aria-hidden={!showOverlay} className={`overlay ${showOverlay ? "visible" : "hidden"}`} viewBox={`0 0 ${imgWidth} ${imgHeight}`} preserveAspectRatio="xMinYMin meet">{showOverlay && overlayPolygons}</svg>
          </div>
        </div>
      </section>
        <section className="fields-panel">
          <h2>Model suggestions</h2>
          <p className="explain">Document: {selectedCase.vision.documentType ?? "unknown"} · {isRejected ? `Rejected: ${selectedCase.vision.error ?? "unknown failure"}` : "Schema accepted; unreviewed, not an approved order"}</p>{selectedCase.vision.notes.map((note, i) => <p className="explain" key={i}>{note}</p>)}{selectedCase.vision.fields ? (<table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Value</th>
                <th>Status</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>{Object.entries(selectedCase.vision.fields).map(([k, v]) => <FieldRow key={`${selectedCase.id}-${k}`} name={k} field={v} />)}</tbody>
          </table>) : <p>No fields or raw model output only.</p>}</section>
        <section className="cer-bars">
          <CERBar label="Vision CER" value={metrics.vision.text.cases.find(cs => cs.case_id === selectedCase.id)?.cer ?? null} />
          <CERBar label="Paddle original CER" value={metrics.paddle_original.text.cases.find(cs => cs.case_id === selectedCase.id)?.cer ?? null} />
          <CERBar label="Paddle enhanced CER" value={metrics.paddle_enhanced.text.cases.find(cs => cs.case_id === selectedCase.id)?.cer ?? null} />
        </section>
        <section className="transcription">
          <h2>Transcription</h2>
          <nav role="tablist" aria-label="Transcription sources">
            <TabButton id="nicrron" label="Nicrron raw" selected={transTab === "nicrron"} onClick={() => setTransTab("nicrron")} />
            <TabButton id="paddleOriginal" label="Paddle original" selected={transTab === "paddleOriginal"} onClick={() => setTransTab("paddleOriginal")} />
            <TabButton id="paddleEnhanced" label="Paddle enhanced" selected={transTab === "paddleEnhanced"} onClick={() => setTransTab("paddleEnhanced")} />
            <TabButton id="reference" label="Reference" selected={transTab === "reference"} onClick={() => setTransTab("reference")} />
          </nav>
          <pre role="tabpanel" id={`${transTab}-panel`} aria-labelledby={`${transTab}-tab`} tabIndex={0} className="transcription-text">{transcriptionText()}</pre>
        </section>
      </> : <p>No case selected.</p>}</article>
    </section>
    <footer>run .venv/bin/python -m ocr.export_viewer after new OCR runs to update snapshot.</footer>
  </main>);
};
export default BenchmarkView;
