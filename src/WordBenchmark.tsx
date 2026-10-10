import { publicAsset } from './publicAsset';
import { useState } from 'react';

type WordResult = {
  id: string;
  reference: string;
  prediction: string | null;
  status: string;
  reading_status: string | null;
  error: string | null;
  exact_match: boolean;
};
export type WordReport = {
  sample_size: number;
  upstream_test_size: number;
  complete: boolean;
  sample_hash: string;
  recovery_note: string | null;
  reference_warning?: string;
  word_agreement?: {
    agreeing_nonblank_crops: number;
    agreeing_matching_label: number;
    agreeing_mismatching_label: number;
  };
  images: Record<string, string>;
  engines: Record<string, {
    model: string;
    recorded: number;
    exact_matches: number;
    exact_match_rate: number;
    strict_exact_match_rate: number;
    character_error_rate: number;
    failed: number;
    missing: number;
    abstained: number;
    median_seconds: number | null;
    p95_seconds: number | null;
    reported_usage: { prompt_tokens: number; completion_tokens: number; receipts: number };
    results: WordResult[];
  }>;
};

export default function WordBenchmark({ report }: { report: WordReport }) {
  const [filter, setFilter] = useState('differences');
  const engines = Object.entries(report.engines);
  const rows = engines[0][1].results.filter(row => filter === 'all' || engines.some(([, engine]) => {
    const result = engine.results.find(r => r.id === row.id);
    return filter === 'errors' ? result?.status !== 'ok' : !result?.exact_match;
  }));
  return <section className="word-benchmark" aria-label="RxHandBD handwriting benchmark">
    <h2>RxHandBD · {report.sample_size} test crops</h2>
    <p>Fixed sample from {report.upstream_test_size.toLocaleString()} upstream test images · {report.complete ? 'Run complete' : 'Partial run; missing cases remain in the denominator'}</p>
    {report.recovery_note && <p className="caveat">{report.recovery_note}</p>}
    {report.reference_warning && <p className="caveat">{report.reference_warning}</p>}
    <div className="word-metrics">
      {engines.map(([name, engine]) => <article key={name}>
        <h3>{engine.model}</h3>
        <strong>{(engine.exact_match_rate * 100).toFixed(1)}% exact label match</strong>
        <p>{engine.exact_matches}/{report.sample_size} labels matched · CER {(engine.character_error_rate * 100).toFixed(1)}%</p>
        <p>Strict match: {(engine.strict_exact_match_rate * 100).toFixed(1)}% · Recorded: {engine.recorded}/{report.sample_size}</p>
        <p>{engine.failed} failed · {engine.abstained} abstained · {engine.missing} missing</p>
        <p>Median {engine.median_seconds?.toFixed(3) ?? 'N/A'}s · P95 {engine.p95_seconds?.toFixed(3) ?? 'N/A'}s</p>
        {name !== 'paddle' && <p>Reported tokens: {engine.reported_usage.prompt_tokens.toLocaleString()} input / {engine.reported_usage.completion_tokens.toLocaleString()} output ({engine.reported_usage.receipts}/{engine.recorded} receipts). Billed cost unknown.</p>}
      </article>)}
    </div>
    {report.word_agreement && <p>Matching nonblank Nicrron readings: {report.word_agreement.agreeing_nonblank_crops}. Of these, {report.word_agreement.agreeing_matching_label} matched upstream labels and {report.word_agreement.agreeing_mismatching_label} differed. This is a word-level diagnostic.</p>}
    <p className="explain">Word crops only; no full-order or fax accuracy claim. References are upstream labels awaiting independent review. Exact match and CER casefold and collapse whitespace; digits and punctuation remain significant. Strict match preserves original casing and spacing. Missing, failed, and abstained readings count as empty text. HTTP/inference latency excludes pacing, queueing, initialization and artifact writes. No confidence threshold, automatic retry, or label-based repair.</p>
    <details>
      <summary>Compare source crops, labels, and predictions</summary>
      <label>Show <select value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="differences">Any label mismatch</option>
        <option value="errors">Errors or missing results</option>
        <option value="all">All sample crops</option>
      </select></label>
      <p>{rows.length} crops shown · Sample {report.sample_hash.slice(0, 12)}…</p>
      <div className="word-table-scroll"><table>
        <thead><tr><th>Original crop</th><th>Upstream label</th>{engines.map(([name, engine]) => <th key={name}>{engine.model}</th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.id}>
          <th scope="row"><img src={publicAsset(report.images[row.id])} alt={`Original word crop ${row.id}`} width={128} height={128} loading="lazy" /><br />{row.id}</th>
          <td>{row.reference}</td>
          {engines.map(([name, engine]) => {
            const result = engine.results.find(r => r.id === row.id);
            return <td key={name} className={result?.exact_match ? 'word-match' : 'word-mismatch'}>
              <strong>{result?.prediction ?? 'No reading'}</strong><br />
              {result?.error ?? result?.reading_status ?? result?.status ?? 'unprocessed'} · {result?.exact_match ? 'Match' : 'Mismatch'}
            </td>;
          })}
        </tr>)}</tbody>
      </table></div>
    </details>
  </section>;
}
