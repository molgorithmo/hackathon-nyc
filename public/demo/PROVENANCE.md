# Mock prescription scans

`clear-rx-scan.png` and `ambiguous-rx-scan.png` were created with the built-in image generation tool for illustrative UI fixtures. They are not real prescriptions, OCR inputs used for evaluation, or measured model outputs. All structured workflow values remain manually authored. The ambiguous image deliberately leaves a birth-date digit and strength unclear and refills blank.

## Generation prompts

### Clear

Generate a portrait grayscale fax scan of a fictional handwritten prescription form, full page, straight overhead, white paper with subtle photocopy noise, printed ruled fields and natural legible black pen handwriting. This is a website demo prop. LARGE clearly legible header and footer 'MOCK PRESCRIPTION — DEMO ONLY — NOT VALID'. No signatures, registration numbers, addresses or actual clinic names. Header 'PillSpark Demo'. Exact handwritten fields: Patient: Maria L. Hernandez; DOB: 04/12/1978; Written: 03/14/2024; Rx: Lisinopril 10 mg; Form: Tablet; Directions: Take 1 tablet by mouth once daily; Quantity: 30 tablets; Refills: 3; Prescriber: Alan R. Whitfield, MD. All text must match exactly, readable. Printed small footer 'Illustrative workflow fixture. Not model output or clinical evidence.' Looks like a scanned prescription document, NOT a typography poster or yellow text card. White background, portrait page fills image.
+
### Ambiguous

Generate a portrait grayscale fax scan of a fictional handwritten prescription form, full page, straight overhead, white paper with subtle photocopy noise, printed ruled fields and natural black pen handwriting. Website demo prop. LARGE clearly legible header and footer 'MOCK PRESCRIPTION — DEMO ONLY — NOT VALID'. No signatures, registration numbers, addresses or actual clinic names. Header 'PillSpark Demo'. Exact fields: Patient: James O. Carter; DOB: 11/0?/1961 (one digit deliberately unreadable); Written: 02/28/2024; Rx: Venlafaxine ER; Strength: an intentionally smudged leading digit that could be 2 or 7, followed by legible '5 mg', do not resolve the ambiguity; Form: Capsule; Directions: Take 1 capsule by mouth every morning; Quantity: 30; Refills: leave field blank with ruled line; Prescriber: Priya Nakamura, DO. Keep all other writing legible and exact. Printed footer 'Illustrative ambiguity fixture. Not model output or clinical evidence.' Looks like a scanned prescription document, NOT a typography poster or yellow text card. White background, portrait page fills image.

