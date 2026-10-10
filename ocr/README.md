# OCR baseline

This package implements OCR experiments and the first deterministic release-gate slice. Start with the dataset limitations in ../data/clinocr/README.md.

## Live image upload

Run the API and frontend in separate terminals:

```sh
.venv/bin/python -m ocr.api
npm run dev -- --host 127.0.0.1
```

Open the frontend's **Live upload** view. Choose one JPEG/PNG (up to 10 MiB and 20 million pixels),
or load the gathered ClinOCR clinical-note example, then select **Extract image**. The image goes
through the real blind GPT-4.1-mini/GPT-4.1 Nicrron pipeline and deterministic release gate.
Keep `NICRRON_API_KEY` in local `.env`; no credential reaches the browser. Model calls are paid.

The local API accepts raw image bytes at `POST /v1/extractions`, with `Content-Type: image/jpeg`
or `image/png`, a UUID `Idempotency-Key`, and `X-PillSpark-Request: 1`. Poll
`GET /v1/extractions/{id}` with the same request header for processing/complete/failed state and
validated readings/decision/signals. Vite proxies the endpoints to loopback port 8765. There is no
CORS or remote binding. One pipeline runs at a time; uploads time out after 15 seconds and
processing after 150 seconds. Failed/late jobs cannot become releases. Reusing an ID with the
same image returns the existing job; a different image returns 409. GET never triggers model calls.

**Check existing result** resumes polling without resubmitting the image. The image preview stays
in browser memory; a full page reload loses the selected file and UI job state. Jobs and full
receipts remain private under `artifacts/api/{id}/`, mode 600, with mode-700 job directories.
Interrupted processing is marked failed after API restart, without retry. Raw provider bodies are
never returned or logged. Retention/cleanup is manual in this local demo; no source image is saved.

Unassessed OCR/quality/support/distribution checks still block automatic release. Candidates are
never automatically selected, readings are not merged, and model scores do not become calibrated
confidence. Live corrections, PDF input, multi-user authentication, calibration, and pharmacy
integration remain outside this slice. The Workflow/Summary saved cases stay separate from live
results. The gathered non-prescription smoke test demonstrates integration/rejection only.

Verify with `.venv/bin/python -m unittest discover -s tests -v`, `npm run test:ui`,
`npm run build`, and `npm run lint`.

## Deterministic release gate

`ocr.release.evaluate_release(primary, verifier, signals=ReleaseSignals(...))` accepts two independently obtained `Extraction` models, or `None` for an invalid/failed response. It makes no model calls and does not modify the inputs. It returns a typed `ReleaseDecision` with `status`, `policy_version`, `document_reasons`, `field_reasons`, and `accepted_order` (present only on `auto-released`). Release accepts an extraction for downstream order entry, not clinical review or dispensing authorization.

Explicit signals are `primary_complete`, `verifier_complete`, both readings' `*_order_count`, `independent_verification`, `ocr_checked`, field-keyed `ocr_contradictions`, `image_quality_passed`, `document_supported`, and `in_distribution`. All checks default to unassessed (`None`); omitted checks block release. Independence is a caller attestation about blind readings of the same input; passing the same object twice is also blocked. Counts must be established per reading; notes are not parsed to infer order count or ambiguity. The caller must surface document concerns in the structured signals.

Policy `ftf-release-v1` requires all ten existing `APPROVAL_REQUIRED_FIELDS`, each with one nonblank value, nonblank source text, `extracted` status, no candidates, and agreement. Text name/drug/form/prescriber fields compare lowercase with collapsed whitespace; other fields only collapse whitespace. Digits, punctuation, units, Sig abbreviations, and date representations are not rewritten. The released order preserves the primary values verbatim. Confidence, OCR readings, and catalogs never fill or select values.

Known non-prescriptions and multiple orders are `rejected`. Missing/ambiguous fields, evidence gaps, disagreement, unknown document types, unassessed checks, and failed quality/support/OCR checks are `exception`. Rejection takes precedence over exception; all failing reasons are retained. Every non-release contains actionable stable codes and no accepted order. Machine-readable output uses the existing camelCase prescription field names.

This is an executable rule baseline, not a calibrated clinical safety policy. Quality/support/OCR signal generation, format/catalog checks, risk thresholds, API orchestration, persistence, and the selective-risk dashboard remain separate work. `tests/fixtures/release_prescription.json` is a saved synthetic unit fixture, not labeled prescription evaluation data. The ten ClinOCR non-prescriptions remain regression evidence only.

## Blind verification and local orchestration

`ocr.verify` decodes/bounds one JPEG/PNG, preserves its bytes and hash, and obtains a blind reading through Nicrron. `DocumentReading` extends the existing extraction schema with required nullable `orderCount`. No primary response, evaluation labels, OCR text, catalog, council context, or previous messages are sent to the verifier. Unknown/multiple-order readings cannot populate dispensing fields. Truncation, refusal, unexpected returned model families, invalid schema, and service failures produce explicit failed receipts; raw responses are preserved without repair or fallback.

`ocr.pipeline.run_pipeline` runs the two readings concurrently and calls the deterministic release gate. Defaults are `openai/gpt-4.1-mini` for primary and `openai/gpt-4.1` for verifier; set `NICRRON_MODEL` / `NICRRON_VERIFIER_MODEL` locally to change requested models. Returned identifiers must match the requested name or its dated snapshot. Receipts include call/provider IDs, input/prompt hashes, prompt version, requested/returned models, completion, usage, and latency. Wrong-image, stale-prompt, wrong-role/model, or duplicate-call receipts cannot release.

```sh
.venv/bin/python -m ocr.pipeline \
  --image data/clinocr/images/template_8_sample_2_normal.jpg \
  --output artifacts/pipeline/my-new-run.json
```

This makes two paid model requests and writes a new mode-600 result file. Existing runs are never overwritten. The output contains both raw receipts, validated readings, actual gate signals, and the final decision. Console output contains only statuses/error codes. Vite denies direct HTTP access to `artifacts/`, `data/`, and test fixtures; the public synthetic viewer snapshot still works. Inside the project, the CLI allows receipts only under `artifacts/`; private locations outside the project are also allowed.

Optional `--checks path.json` accepts `EvidenceChecks` with `input_sha256`, `ocr_checked`, `ocr_contradictions` (field-keyed explanations), `image_quality_passed`, `document_supported`, and `in_distribution`. The hash must match before any paid call. Omitted checks remain unassessed and block automatic release even when both models agree. This slice does not generate or calibrate those checks or run PaddleOCR automatically. Completeness, order counts, and independence derive from the actual two receipts, not user-supplied pass flags.

Live regression: `artifacts/pipeline/20261010-blind-smoke.json` records two requests on one public synthetic ClinOCR non-prescription. The primary was rejected by schema validation; the verifier returned a valid non-prescription reading. Final decision: `rejected`, with no order. This verifies transport/routing, not prescription accuracy or calibration. No live positive prescription release has been demonstrated.

## RxHandBD word benchmark

`ocr/benchmark_words.py` freezes 100 of the 1,115 upstream test crops before inference, using SHA-256 ranks of version/ID/image hash; labels are not used for selection or sent in requests. `data/rxhandbd/benchmark-sample-v1.json` binds the selection to the full source manifest. Input, sample, prompt/schema, version, and model changes reject cached receipts. No tuning or training uses this test sample.

```sh
.venv/bin/python -m ocr.benchmark_words --run --output artifacts/words/rxwords-v1-paced
.venv/bin/python -m ocr.benchmark_words --output artifacts/words/rxwords-v1-paced
.venv/bin/python -m ocr.export_viewer \
  --regression artifacts/regression/clinocr-blind-v1 \
  --words artifacts/words/rxwords-v1-paced
```

`--run` makes paid Nicrron requests only for missing receipts (GPT-4.1-mini and GPT-4.1), then runs cached CPU `en_PP-OCRv5_mobile_rec` directly on the same crops. This tests recognition only, not page detection. Use `--engine mini`, `full`, or `paddle` to run one engine. Requests start at least 1.5s apart (40/minute); raw errors are retained without automatic retry, repair, model fallback, or label-based correction. Scoring/export do not call models. Receipts are mode-600 files outside public paths.

Report exact normalized word/phrase match, strict exact match, corpus CER, failure/abstention/missing counts, HTTP/inference median/P95, and reported token usage. Normalized metrics casefold and collapse whitespace only. Every selected crop stays in the denominator; failures/missing/abstentions score as empty text. HTTP/inference latency excludes request pacing, queueing, model initialization, and artifact writes. Provider billing remains unknown. Upstream labels are unreviewed; this is not prescription/fax accuracy, calibration, or evidence that matching models are safe to release.

The first run (`artifacts/words/rxwords-v1`) burst four concurrent requests and hit HTTP 429 after 60 successful requests (40 mini and 100 full rate-limit errors). It remains unchanged. The separate paced recovery directory reuses its 60 successful Nicrron and 100 Paddle receipts, then attempts the remaining 140 Nicrron readings once. `recovery.json` records that provenance; the viewer explicitly labels the recovery. Do not treat the rate-limited run as an isolated comparison of model recognition accuracy.

Completed paced comparison: GPT-4.1-mini 34% normalized exact match / 42.3831% CER (13 abstentions); GPT-4.1 36% / 41.7798% (11 abstentions); Paddle 19% / 45.7014% (no abstentions). All engines have 100 receipts, with no remaining service failures. Strict exact matches: 27%, 34%, 17%. Both Nicrron models agreed on 35 nonblank readings; 27 matched upstream labels and eight differed. Review labels/legibility independently before attributing every discrepancy to the models. No calibration or release policy is selected from this test sample.

Post-run agent spot-checks found apparent source-label mismatches (P0049 and P0164); [notes](../data/rxhandbd/label-review-notes.md) retain the observations without changing gold labels. The report/viewer flags reference quality. These scores measure upstream-label agreement and cannot yet establish trustworthy OCR accuracy; shared readings that differ from a label are not automatically recognition errors.

## Gathered-data regression

Additional handwriting data is available separately: [RxHandBD v1](../data/rxhandbd/README.md), 5,578 word crops with source labels (4,463 train / 1,115 test). Recreate with `.venv/bin/python -m ocr.prepare_rxhandbd`. Its separate 100-crop benchmark above cannot substitute for full prescription/fax examples. The ClinOCR commands below continue to use only the original ten documents.

Use the ten downloaded ClinOCR documents for the current demo. No new images are generated. Run the blind pipeline once, then reuse its saved receipts:

```sh
.venv/bin/python -m ocr.regression --run
.venv/bin/python -m ocr.regression
.venv/bin/python -m ocr.export_viewer --regression artifacts/regression/clinocr-blind-v1
```

Only `--run` makes paid requests (two per missing case); existing failures are retained without retries. A matching previously saved smoke receipt is reused for one case, with batch latency explicitly unavailable. Image/model/prompt/policy mismatches refuse cached receipts. Use a new `--output` directory for another experiment. Receipts and `metrics.json` are private mode-600 artifacts; the viewer recomputes an allowlisted summary without exporting raw model readings.

The report measures non-prescription blocking, per-model schema failures, reported token usage, and processing latency (ingestion + concurrent calls + gate). Missing cases remain in the block-rate denominator; missing usage/timing stays missing. Billing is unknown. All ten cases are synthetic non-prescriptions and quality/OCR/support checks remain unassessed, so blocking cannot establish prescription accuracy, calibrated release coverage, or clinical safety. The saved prescription unit fixture is software-test input only.

Current run: 8 rejected, 2 exceptions, 0 released. Primary schema-valid 3/10 (5 invalid extractions, 2 gateway errors); verifier 10/10 (8 clinical-other, 2 unknown). Median processing 7.877s / P95 30.353s across 9 timed cases. Usage receipts cover 18/20 calls. The existing viewer displays these decisions separately from the earlier single-model OCR baseline.

## Setup

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-ocr.txt
cp .env.example .env
```

Set NICRRON_API_KEY in .env. The key stays on the local Python side and is ignored by Git. The default model is pinned to openai/gpt-4.1-mini; automatic model routing is disabled. Only the existing public synthetic ClinOCR images are sent in this benchmark.

## Run

```sh
.venv/bin/python -m ocr.prepare_clinocr
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ocr.benchmark vision --limit 1
.venv/bin/python -m ocr.benchmark vision
.venv/bin/python -m ocr.benchmark paddle
.venv/bin/python -m ocr.evaluate
.venv/bin/python -m ocr.council
```

The council follows Karpathy's three-stage pattern: independent proposals, anonymized peer
ranking, and a chairman synthesis. It sends only the files in `ocr.council.ALLOWED_FILES` through
Nicrron and writes the complete audit trail under `artifacts/council/<timestamp>/`. Council output
is architectural advice; it never participates in prescription extraction or approval.

PaddleOCR downloads its public pretrained models on first use. Model caches stay in .cache/. The OCR comparison uses PP-OCRv5_mobile_det and en_PP-OCRv5_mobile_rec on CPU; no training or fine-tuning is performed. OpenCV applies small-angle deskew, denoising, CLAHE, and unsharp masking. Each enhanced page keeps forward/inverse transforms so evidence polygons map back to the original image. Large rotation and curved-page correction are outside this baseline.

## Inspect output

For a visual report, export the saved results and start the React viewer:

```sh
.venv/bin/python -m ocr.export_viewer
npm run dev -- --host 127.0.0.1
```

Open the local URL printed by Vite. The viewer includes aggregate/per-case reading-error charts, source/enhanced images, Paddle evidence overlays, field evidence, validation failures, and transcription comparisons. Refresh reloads the exported snapshot without making model calls. Export again after new benchmark runs. `public/run/` contains only allowlisted public synthetic benchmark results and images; it is ignored by Git. The viewer is read-only and cannot approve prescriptions.

- artifacts/baseline/vision/: validated extraction or explicit rejection per case.
- artifacts/baseline/vision/raw/: untouched provider response, including outputs the validator rejected.
- artifacts/baseline/paddle/original/ and paddle/enhanced/: text, scores, and source polygons.
- artifacts/baseline/*_enhanced.png: processed page images.
- artifacts/baseline/metrics.json: reading errors, non-prescription rejection, latency, and estimated cost.

Existing vision results are reused to avoid accidental charges. Use --retry-service-errors for transport errors; validation failures are preserved. Use a new --output directory for a new experiment. Do not use rejected output as an order.

## Contract and scoring

schema.py mirrors the ten frontend fields. Extraction statuses are extracted, needs-review, and missing; confirmed is reserved for humans. Non-prescriptions cannot populate dispensing-order fields. Multiple candidates require a null selected value. Every asserted value needs source text, though schema validation alone cannot prove that evidence is true. Scores remain explicitly uncalibrated.

Full-page character error rate uses casefolded text with collapsed whitespace; it keeps digits, punctuation, and reading order significant. Failed/missing outputs remain in the denominator as empty transcriptions. Raw reading quality is reported separately from validated acceptance. Identity correctness uses upstream transcription labels and still needs independent visual review. All ten cases are non-prescriptions: positive drug accuracy and ambiguity recall are unavailable.

Vision latency measures the HTTP request. Paddle latency measures inference; it excludes image enhancement and first-use downloads/model initialization. Cost is a catalog estimate; billed cost is unknown. Raw provider errors and attempts are retained. Zero-shot evaluation never passes the source transcription or labels to the model.

## References

- [Nicrron API compatibility](https://nicrron.ai/docs/quickstart)
- [Nicrron model catalog and rates](https://nicrron.ai/docs/models)
- [PaddleOCR installation](https://www.paddleocr.ai/main/en/version3.x/installation.html)
