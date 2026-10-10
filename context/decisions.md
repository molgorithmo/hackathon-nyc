# Decisions

## D-001: Build the PillSpark Fax to Fill track

We are focusing on dependable straight-through prescription order entry, with explicit exception handling when the system cannot support automatic release.

## D-002: Never guess critical prescription fields

Missing or ambiguous values must be marked `Needs Review` or `Unable to determine`. Approval remains blocked until critical issues are resolved.

## D-003: Start with ClinOCR

ClinOCR will support initial development and evaluation. We will account for its mismatch with real pharmacy fax traffic when describing results.

## D-004: Use a two-path extraction pipeline

PaddleOCR will provide raw text, locations, and confidence. A vision model through Nicrron will extract structured candidates from the original and enhanced images. Disagreement triggers review.

## D-005: Use Jev after OCR

Jev may classify ambiguity, score candidates, or decide whether human review is required. It will not replace the OCR or vision model.

## D-006: Do not fine-tune initially

First establish a baseline, evaluation set, and recurring failure patterns. Fine-tune only if preprocessing, prompting, validation, and routing do not solve those patterns.

## D-007: Keep the Ninoo output for review

The Ninoo-generated scaffold may be reused, corrected, or replaced. It is not a required runtime dependency.

## D-008: Use Ponytail for project implementation

Use the Ponytail skill to prefer the smallest sufficient implementation while preserving validation, security, accessibility, error handling, and meaningful tests.

## D-009: Treat ClinOCR as a synthetic smoke test

The official release uses synthetic clinical documents. The ten selected upstream evaluation images are non-prescription notes/reports; source images and hashes are preserved. Use them to measure reading quality and inappropriate order extraction. Do not claim positive prescription accuracy. Locate existing prescription images and independently review labels before evaluating the core demo.

## D-010: Preserve failures and avoid automatic enhancement

The zero-shot baseline pins Nicrron `openai/gpt-4.1-mini`; it never receives evaluation labels. Save raw responses and validation failures. Non-prescriptions cannot populate order-specific fields, and uncertain candidates cannot silently become selected values. Model confidence stays null unless supplied, and OCR scores are uncalibrated. Full approval rules remain FTF-05.

PaddleOCR enhancement worsened eight of ten cases (aggregate character error rate 49.0% to 53.8%). Keep originals as the default; preserve enhancement as an explicitly scored experimental path. No fine-tuning or prompt tuning on these evaluation examples.

## D-011: Prefer Nicrron credits for model work

The user reports $250 in Nicrron credits and wants to conserve Codex chat tokens. Prefer the configured Nicrron API for project model calls and bounded code-drafting work, with local review and tests before applying generated code. Do not expose the key in browser code. Nicrron usage is billed separately; it does not pay for the Codex conversation. Keep chat/tool output concise and reuse saved results. No account balance has been independently verified.

## D-012: Optimize for straight-through order entry

Clear, supported prescriptions should be released automatically into downstream order entry. Human confirmation is not required on the happy path. Missing, ambiguous, conflicting, multi-order, unreadable, or out-of-distribution cases enter an exception path or are rejected; they are never silently guessed.

Release approves the extracted record for downstream entry. It does not claim to replace legally required dispensing verification or clinical appropriateness review.

## D-013: Earn automatic release with held-out calibration

Automatic release requires independent blind verification, deterministic validation, evidence checks, and a versioned risk policy calibrated on labeled prescriptions. Model agreement and self-reported confidence are signals, not proof. Select thresholds on a calibration split and report whole-order accuracy, critical false accepts, straight-through coverage, exception recall, selective risk, sample size, and uncertainty on a locked test split.

## D-014: First executable release policy is a deterministic rule baseline

`ocr/release.py` implements `ftf-release-v1` without network, council, OCR-engine, database, or UI dependencies. Its typed decision is `auto-released`, `exception`, or `rejected`, with field/document reasons and an accepted order only on release. It requires all ten existing fields, nonblank evidence, no candidates, conservative primary/verifier agreement, and explicit passing completeness, independence, OCR, image-quality, support, and distribution checks. Unassessed signals block release. Non-prescriptions/multiple orders are rejected; other failed checks enter exception. Original values are preserved and inputs are untouched.

The caller is responsible for producing truthful structured signals and blind readings of the same input; the pure gate cannot establish their provenance. No model-confidence threshold or calibration claim is introduced. Runtime automatic release remains unconnected pending blind verification, labeled prescriptions, calibration, and orchestration.

## D-015: Blind verification and CLI orchestration use separate image-only calls

`ocr/verify.py` sends the original image independently to primary `openai/gpt-4.1-mini` and verifier `openai/gpt-4.1` through Nicrron. Both identifiers were verified against the live catalog. Each returns the existing fields plus explicit nullable `orderCount`. No primary answer, labels, OCR, catalog, or council context enters the verifier request. Failures and raw responses are retained; no automatic model fallback or schema repair is used.

`ocr/pipeline.py` runs both calls concurrently and feeds the deterministic gate. It binds receipts/evidence checks to the input hash and checks role, requested model, prompt version/hash, distinct call IDs, and duplicate provider IDs. OCR/quality/support/distribution checks remain explicit, hash-bound inputs; unknown checks block automatic release. The CLI stores mode-600 receipts outside public/dist and Vite blocks artifact/source-data URLs.

One live synthetic non-prescription regression was rejected: primary failed schema validation and the blind verifier classified it as a non-prescription. This demonstrates transport and rejection, not positive prescription accuracy. Calibration, check generation, persistence, API, and UI integration remain outstanding.

## D-016: Continue with the gathered data

The user explicitly requested using existing examples rather than waiting for real prescriptions. Freeze the ten downloaded ClinOCR images; do not generate evaluation data or fetch another dataset for this slice. Run the blind pipeline across them and report non-prescription blocking, schema/service failures, latency, and reported token usage. Reuse matching saved receipts, preserve failed outputs, and keep missing cases in the denominator. Unknown checks still block release.

Prescription whole-order accuracy, critical-field false accepts, release coverage, and threshold calibration remain unmeasurable on this set. Saved synthetic unit fixtures exercise release/exception software branches only. This changes the demo's available-data scope; it does not establish clinical readiness or remove the later need for positive labeled data.

## D-017: Add RxHandBD as a separate word-recognition dataset

The user's subsequent request to add data authorizes downloading an existing dataset. The author's Zenodo v1 RxHandBD archive is accessible and publisher-checksummed; its record API declares MIT. Import its 5,578 unchanged word crops and labels, preserving 4,463 train / 1,115 test. Record source/version/license, source CSVs, metadata, per-image hashes, and original dimensions. Do not silently substitute the Mendeley v3 variant. No exact image hashes cross the supplied split; writer/source-prescription separation is unverified.

Keep this dataset separate from the ten-case ClinOCR regression and the prescription schema. Use it for handwriting OCR only; do not manufacture full orders from isolated words or claim fax/release accuracy. Its upstream labels need independent review. No model calls or benchmark scores are introduced by the import. The whole-prescription Mendeley candidate remains unavailable (public download metadata returned 403).

## D-018: Freeze a test-only word-recognition comparison

`ocr/benchmark_words.py` selects 100 of 1,115 RxHandBD test crops using fixed SHA-256 ranks of version/ID/image hash, independently of labels. The selection file binds the complete dataset manifest before calls. Compare GPT-4.1-mini, GPT-4.1 through Nicrron, and cached CPU `en_PP-OCRv5_mobile_rec` on unchanged crops. This is recognizer-only evaluation, not page detection or complete-order extraction. Prompts request literal text with explicit abstention; labels, other readings, catalogs, and confidence never select a value. Do not tune on these examples.

Score normalized exact match (casefold/whitespace only), strict exact match, corpus CER, and failures/abstentions/missing counts across every selected image. Preserve digits/punctuation. Record HTTP/inference latency and reported usage; billing is unknown. Bind cached receipts to the image/sample/prompt/schema/model/version. Export only a recomputed summary and selected word crops; raw provider responses stay private.

The first four-worker run produced 140 HTTP 429s after 60 successful requests. Preserve it in `artifacts/words/rxwords-v1`. A separate `rxwords-v1-paced` recovery reuses successful receipts and runs only the remaining readings, with starts spaced 1.5s apart (40/minute); this is explicit recovery, not a hidden retry or label-based repair. Keep both reports and recovery provenance. No prescription accuracy, calibration, or automatic-release claim follows from this experiment.

Post-run agent spot-checks found suspected image/label mismatches in P0049 and P0164. Preserve observations in `data/rxhandbd/label-review-notes.md` and flag reference quality in the viewer/report. Do not change gold labels using model agreement. Current exact match/CER measure agreement with upstream labels; trusted OCR accuracy requires independent label adjudication. Eight identical nonblank Nicrron readings differ from labels, which is not proof that those readings are wrong.

## D-019: Connect live uploads without weakening the release gate

The user requested connecting the existing extraction pipeline to the UI before considering Jev. Add a loopback-only standard-library HTTP API and a separate Live upload view in the existing React app. Use asynchronous POST/GET jobs with UUID idempotency, one active pipeline, bounded processing, hash-bound original images, safe errors, and private saved receipts. Keep unknown OCR/quality/support/distribution checks blocking; do not turn them into passing attestations from browser inputs. Live corrections and release mutation endpoints are outside this first connection. Show separate primary/verifier readings, no merged values, no inferred calibration, and no runtime council or Jev call.

Use atomic private JSON job files for the single-user local demo rather than introducing SQLite in this slice. Later multi-user revisions, audit, and exception correction still need the stronger persistence/API contract in the target approach. Source images remain browser-local while model receipts/jobs are stored privately; no automatic retry after restart or provider failure. The saved positive workflow examples remain illustrative, distinct from real API outcomes. Current data still cannot establish prescription-release accuracy.
