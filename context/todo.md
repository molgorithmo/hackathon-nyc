# To Do

Work top to bottom. Details: [todo-context.md](todo-context.md).

## 1. Prove extraction

- [x] FTF-01 Freeze the ten gathered ClinOCR cases for the demo regression.
- [x] FTF-01A Add RxHandBD word images with upstream labels and splits.
- [ ] FTF-02 Review existing labels and document evaluation gaps.
- [x] FTF-03 Run one Nicrron vision model on the labeled set.
- [x] FTF-04 Compare PaddleOCR and preprocessing against the baseline.
- [x] FTF-04A Benchmark OCR on a fixed RxHandBD test sample.

## 2. Complete the workflow

- [ ] FTF-05 Implement calibrated automatic release and exception routing.
- [x] FTF-06 Expose the extraction pipeline through an upload API.
- [x] FTF-06A Connect live uploads and backend decisions to the UI.
- [ ] FTF-07 Connect straight-through status and the exception-resolution UI.
- [ ] FTF-08 Record automatic releases/corrections and export orders with an audit trail.

## 3. Verify and demo

- [ ] FTF-09 Score the gathered cases and test workflow failures.
- [ ] FTF-10 Add PRISM tracing, guardrail, evaluator, and grounded lookup.
- [ ] FTF-11 Rehearse clear and ambiguous cases end to end.
