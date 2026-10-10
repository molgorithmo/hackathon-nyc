# Initial label spot-check

Agent visual inspection after the frozen benchmark; not independent ground-truth adjudication. Original labels, images, sample, and predictions are unchanged. Do not replace labels with model outputs or tune on these test cases.

- **P0049**: upstream label `Omep`; [original crop](images/test/P0049.jpg) visually appears to say `Rotac`. Both Nicrron readings were `Rotac`.
- **P0164**: upstream label `Xyflo`; [original crop](images/test/P0164.jpg) visually appears closer to `Zo-mups`. The three engines disagree on parts of the writing.

These are suspected image/label mismatches, not corrected gold labels. Review source pairings and legibility independently before attributing benchmark discrepancies to recognition errors. Current percentages report agreement with upstream labels and cannot establish trustworthy OCR accuracy. The 8 shared Nicrron readings that differ from labels cannot all be called incorrect without that review.
