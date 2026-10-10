# Task Context

## Working order

Use the ten ClinOCR examples already gathered, as requested by the user. Do not block the hackathon slice on acquiring real prescriptions or generate evaluation images. Finish image-to-decision orchestration and its exception path using this regression set; independently reviewed positive data remains necessary before claiming prescription accuracy or calibrated release. Check off tasks only when their stated result exists.

The later request to add more data authorizes the separate RxHandBD import below. It does not replace ClinOCR or change its recorded results.

## FTF-01: Verify the data

Complete for the available-data demo scope: ten unchanged upstream evaluation images are frozen with provenance and hashes in `data/clinocr/manifest.json`. ClinOCR access and MIT terms were verified; the release is synthetic and the selected documents are non-prescriptions. The previously investigated Mendeley candidate was not downloaded (403), so it is outside this run. No new data collection or generation is required for the current slice. See `data/clinocr/README.md`.

## FTF-01A / FTF-04A: Add and evaluate handwriting crops

Imported the author's [RxHandBD Zenodo v1](https://zenodo.org/records/18478741) archive: 5,578 unchanged images and upstream text labels, preserving 4,463 train / 1,115 test. `ocr/prepare_rxhandbd.py` pins the publisher MD5 and writes per-image SHA-256, original dimensions, labels, and split roles into `data/rxhandbd/manifest.json`. The record API declares MIT; metadata and source CSVs are saved privately under `upstream/`. This is not Mendeley v3 (different resolution/license). Zero exact image hashes cross the split, but writer/source-prescription independence is unknown.

Complete: import plus the frozen 100-crop test-only benchmark. `data/rxhandbd/benchmark-sample-v1.json` records deterministic SHA-256 selection and the source manifest hash. `ocr/benchmark_words.py` makes label-free Nicrron calls and runs the cached Paddle English recognizer directly on original crops. Metrics in `artifacts/words/rxwords-v1-paced/metrics.json`: GPT-4.1-mini 34/100 normalized exact matches, 42.3831% CER, 13 abstentions; GPT-4.1 36/100, 41.7798% CER, 11 abstentions; Paddle 19/100, 45.7014% CER, no abstentions. All 300 final receipts exist with zero remaining service failures. Strict exact matches: 27, 34, 17. HTTP/inference medians: 0.89355s, 0.7492s, 0.05315s; excludes pacing/queueing/initialization/writes. Nicrron reports 65,000 input + 2,309 output tokens across 200 successful receipts; billing unknown.

Initial burst errors (140 HTTP 429s) remain in `artifacts/words/rxwords-v1`; the explicit paced recovery reused 60 successful Nicrron and 100 Paddle receipts and retried only missing readings in the new directory. Calls now start 1.5s apart; no automatic retries, prompt changes, fallback, or label-based repairs. The viewer includes recovery provenance, all metrics, original crops, labels, predictions, and mismatch/error filters; it exports no raw receipts. Nine new offline tests cover sampling, denominators, normalization, abstentions, provenance, blindness, invalid/truncated responses, safe export, and agreement. All 67 Python tests pass. The benchmark build passed before concurrent workflow edits; the final full-app build is currently blocked by unrelated `src/App.tsx` missing `ConfidenceFilter`/`ConfidenceBadge` definitions and unused workflow declarations. Lint exits successfully with workflow warnings; the benchmark viewer was verified in-browser. No workflow source was changed for this benchmark.

Both Nicrron models produced the same nonblank reading on 35 crops: 27 matched upstream labels, eight differed. This is a word-level diagnostic, not calibrated release risk. Crops cannot measure complete-order accuracy, automatic-release coverage, or fax robustness; upstream labels and writer/source-prescription separation remain unreviewed. Next work belongs to FTF-02: review mismatches and source legibility independently before treating label disagreement as model error or changing prompts. Do not tune on this test sample or silently replace labels with model outputs.

Post-run agent spot-checks found apparent reference problems: P0049 is labeled `Omep` but the image appears to read `Rotac`; P0164 is labeled `Xyflo` but appears closer to `Zo-mups`. See `data/rxhandbd/label-review-notes.md`. These are unadjudicated findings, not corrected gold. The report/viewer flags them prominently. Benchmark rates measure upstream-label agreement; dependable OCR accuracy and the correctness of shared model disagreements are not established. Independent review remains FTF-02.

## FTF-02: Define the truth and contract

Label 10 representative documents at field level, including unreadable and missing values. Start with the existing `src/domain/types.ts`; add source text, evidence locations, and explicit dose/route/frequency only where needed. Agree which missing or uncertain fields block approval, including patient identity. Separate model suggestions from human confirmation. Keep evaluation examples out of prompt examples.

Partial: ten starter annotations derived from upstream transcriptions are in `data/clinocr/labels.json`. Python and TypeScript share ten field keys; explicit missing/ambiguous statuses and evidence are implemented. The release gate requires all ten fields. Original-image polygons are available in Paddle results. Remaining: independent visual legibility review. There are zero positive prescription labels; the saved synthetic prescription fixture tests software branches only and is not benchmark evidence.

## FTF-03: Establish the baseline

Confirm Nicrron vision access and run one model on the originals. Save validated structured output, raw response, latency, and cost. Missing values stay null; ambiguous readings retain candidates. Reject malformed responses and report service failures. Keep the provider key on the backend. Done when the 10 cases have field-level results we can compare with labels.

Complete: pinned `openai/gpt-4.1-mini`, ten live responses saved under `artifacts/baseline/vision/`, with raw output, usage, estimated cost, and latency. One gateway 502 was retried successfully and its failed attempt retained. Seven responses were rejected for inappropriate order fields; three passed schema validation, which does not mean clinically correct or approved. Raw identity correctness was 14/20; document classification 8/10. Estimated successful-request cost was $0.0301, actual billing unknown. Median request latency was 6.93 seconds. Full-page character error rate was 20.4%.

## FTF-04: Measure the second path

Run PaddleOCR for text, locations, and its native scores. Compare original versus OpenCV-enhanced input on the same cases. Preserve original evidence and coordinate mapping. Keep transformations that help; do not assume enhancement improves handwriting. Compare OCR and vision readings, retaining conflicts. Agreement and model-reported confidence are signals, not calibrated correctness probabilities.

Complete: CPU mobile PP-OCRv5 detector and English recognizer ran on ten originals and ten enhanced pages. Aggregate character error rate: 49.0% original, 53.8% enhanced; enhancement improved two and worsened eight. Keep original input as default. Tokens, native scores, and mapped evidence polygons are saved in `artifacts/baseline/paddle/`; enhanced PNGs sit alongside the report. Results are in `artifacts/baseline/metrics.json`. Latency excludes enhancement/model initialization. Cross-engine field reconciliation belongs to FTF-05; this task measures the reading paths independently.

## FTF-05: Calibrate automatic release

Build a versioned automatic-release gate using blind independent verification, required fields, malformed values, conflicting readings, image/document support, and drug/strength plausibility. A catalog match does not prove what the fax says. Release supported clear orders without human confirmation; route or reject missing, ambiguous, conflicting, multi-order, unreadable, and out-of-distribution cases. Select thresholds on a separate calibration set and enforce the gate on the backend. Start with explicit rules; add Jev only if measured routing errors justify it.

Partial: `ocr/release.py` provides a pure deterministic gate (`ftf-release-v1`), typed signals/decisions, stable field/document reason codes, and detached accepted orders. Tests use a saved synthetic prescription fixture and exercise release, conflicts, missing fields/evidence, candidates, OCR contradiction, quality/support/distribution, incomplete checks, rejection, independence, normalization, and input immutability. The gate itself makes no external calls and uses no runtime council. FTF-05 stays open for labeled prescription data, check generation, format/catalog checks, and calibrated thresholds. Blind verification is implemented below; API orchestration and the judge-facing selective-risk dashboard remain later slices.

Next slice implemented: `ocr/verify.py` adds blind Nicrron readings with explicit order counts and complete/invalid receipts; `ocr/pipeline.py` concurrently runs primary/verifier and invokes the gate using image-bound checks. Verifier requests never receive primary outputs. Fourteen additional offline tests cover blindness, ingestion, truncation, schema/service failures, fallback rejection, default blocking, and stale/cross-input/duplicate receipts. Live result: `artifacts/pipeline/20261010-blind-smoke.json`, a rejected public synthetic non-prescription (invalid primary, valid verifier). FTF-05 remains open for positive labeled data, OCR/quality/support check generation, format/catalog rules, and threshold calibration. No API or runtime council was added.

## FTF-06: Connect ingestion

Implemented in `ocr/api.py` using the standard library and existing dependencies. Run `.venv/bin/python -m ocr.api`; Vite proxies `/v1/extractions` to loopback port 8765. `POST /v1/extractions` accepts original JPEG/PNG bytes (10 MiB/20M-pixel limits), a UUID `Idempotency-Key`, and `X-PillSpark-Request: 1`. `GET /v1/extractions/{id}` returns processing/complete/failed, input hash, timestamps, and allowlisted validated readings/decision/signals. No raw provider response or key is returned. One paid job runs at a time; jobs have a 150-second deadline. Timeouts cannot become later releases. Duplicate IDs reuse saved results; conflicting images return 409. Processing jobs become failed after restart without automatically repeating calls. Private mode-600 job/receipt files under mode-700 `artifacts/api/` directories are blocked by Vite. Single-user local demo only: no production auth, PDF support, source-image persistence, or correction/release endpoint.

## FTF-06A: Connect live uploads

`src/LiveUploadView.tsx` and `src/services/liveExtractionService.ts` connect the real backend to the existing decision panel. The Live upload view shows the original image, processing/failure states, actual reasons, source evidence, and separate primary/verifier readings. Values are never merged, ambiguous candidates remain unselected, and model scores are not displayed as calibrated confidence. Client and server bind results to the original image hash. Check existing result only polls GET and spends no further model calls. The saved Workflow/Summary and Benchmark views retain their separate scope. A gathered synthetic ClinOCR note can be loaded from existing viewer assets; it is not prescription accuracy evidence.

Live browser smoke: job `9127ac30-873b-491e-8572-0a00693931ee` completed as rejected, with primary `INVALID_EXTRACTION` and a valid non-prescription verifier. No accepted order or order fields were displayed. Reopening through GET left the private pipeline receipt hash/mtime and job count unchanged. API receipts remain private; screenshot: `artifacts/live-upload.png`. Ten new Python API tests cover ingestion, idempotency/restart, bypass/foreign requests, deadlines/busy capacity, safe failures, and rejection. All 77 Python tests, six UI adapter tests, build, and lint pass. Calibration/check generation and persisted correction workflows remain separate tasks.

## FTF-07: Connect straight-through and exceptions

Partial: live upload now renders real backend decisions, processing/failure states, source evidence, and separate readings through the existing decision panel. Saved Workflow cases still illustrate correction and revalidation. Remaining: connect exception correction to backend revision checks and persisted audit events; do not apply saved-case correction actions to live jobs.

Partial: the broken scaffold has been replaced with a read-only results viewer using the saved ten-case run. `ocr.export_viewer` exports only allowlisted results and public synthetic images into ignored `public/run/`. The UI shows charts, filtering, zoom, original/enhanced OCR overlays, field evidence, rejected raw suggestions, and reference transcriptions. Build and lint pass; exporter tests preserve rejected status and exclude unrelated record keys. Upload, automatic-release status, exception editing, resolution, and audit history remain outstanding. The detailed editing UI is for exceptions; clear cases should show their automatic-release decision and evidence without routine confirmation. Nicrron drafted the initial UI; local review corrected hook usage, status mapping, evidence coordinates, and layout. The successful streamed drafting request reported 905 input and 4,683 output tokens; earlier gateway 502 requests have unknown billing. This drafting usage is separate from the displayed OCR benchmark cost.

## FTF-08: Preserve the decision history

Retain original extraction, each correction, reviewer identity, and timestamps. Approval revalidates the current values and produces JSON tied to the reviewed document. Corrections after approval require a new review. A demo reviewer name is not production authentication.

## FTF-09: Evaluate failures

Available-data regression complete: `ocr/regression.py` reuses hash/model/prompt/policy-matching receipts and calls Nicrron only for missing cases with `--run`. All ten gathered cases were processed: eight rejected, two exceptions, zero releases. Primary schema-valid 3/10, verifier 10/10; failures are retained. Processing median 7.877s, P95 30.353s over nine timed cases; the reused receipt has no batch timing. Reported usage exists for 18/20 readings and actual billing is unknown. Metrics are in `artifacts/regression/clinocr-blind-v1/metrics.json`; the existing viewer displays decisions/reasons and recomputes the summary without raw readings. Six offline regression tests cover denominator handling, inappropriate releases, absent positive metrics, input binding, missing usage/timing, and safe viewer export. All 55 Python tests, build, and lint pass. Prescription accuracy/coverage are N/A on these non-orders; unknown checks block release. This task stays open for API/workflow failure tests and later positive-data selective-risk evaluation.

Create development, calibration, and locked test splits grouped by source/template. Report exact whole-order accuracy among automatically released records, critical-field false accepts, straight-through coverage, exception recall, selective risk, calibration quality, latency, and cost. Keep unreadable cases in the denominator and report sample-size uncertainty. Test API failures, release-gate bypass attempts, stale revisions, and corrections after release. Report exception-corrected results separately from automatic results.

## FTF-10: Demonstrate sponsor requirements

Confirm the actual PRISM SDK and event requirements before wiring it. Trace the extraction/review flow, guard at least one input, evaluate a classified output, and ground a drug-catalog claim through its knowledge base. Exercise each live. Avoid sending identifiable patient data in traces.

## FTF-11: Rehearse the demonstration

Use labeled examples: one clear prescription that is automatically released, one genuinely uncertain prescription that enters the exception path, and one unsupported document that is rejected. Show the versioned release reasons, evidence, correction audit where applicable, exported order, and locked-test coverage/error dashboard. If the source cannot resolve ambiguity, reject or request clarification instead of forcing a candidate choice. State what is mocked and what has been measured.

## Deferred scope

Fine-tuning, multiple vision providers, full pharmacy integrations, production authentication, and UI polish wait until the core workflow passes evaluation. Jev remains optional. Clinical deployment readiness is outside this hackathon demo.
