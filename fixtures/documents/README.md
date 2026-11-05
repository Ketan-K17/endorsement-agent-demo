# Fixture documents

Test documents for the demo and its evals: realistic layouts, fake data (ADR-0016). Templates and the script that fills them live in the untracked `private_docs/` at the repo root and never enter git. Only the finished files go in the folders here.

Built so far: cases 01, 03 and 05, except the optional `nominee_id`. A policy copy is two files, `policy_copy` and `policy_copy_p2`. An RC is one image, front above back. RC, Aadhaar and PAN fixtures carry a SPECIMEN mark.

## How the folders work

One folder per **case**. A case is one customer's story, so every document in it must agree with the others (same reg no, same names, same policy no). Fill `personas.yaml` first, then edit each document so it matches the persona for its case.

Use the exact filenames below (extension `.png` or `.jpg`; no PDFs, see rule 7). Missing files are fine where marked "optional"; they are the point of some cases.

| Case | Used for | Files |
|---|---|---|
| `case_01_owner_transfer_clean` | change-of-owner, happy path | `policy_copy`, `rc_old_owner`, `rc_new_owner`, `aadhaar_front`, `aadhaar_back` (new owner), `pan` (new owner), `transfer_form` (Form 29/30 or signed transfer letter) |
| `case_02_owner_transfer_degraded` | change-of-owner, doc-triage evals | same as case_01 but: `rc_new_owner` blurry, `pan` cropped, `transfer_form` **absent** |
| `case_03_nominee_update` | nominee-update | `policy_copy`, `aadhaar_front`, `aadhaar_back` (policyholder), `nominee_id` (optional) |
| `case_04_name_correction_marriage` | name-correction with a legal name change | `policy_copy` and `rc` (old name), `aadhaar_front`, `aadhaar_back` (new name), `name_change_proof` (marriage certificate or gazette notification) |
| `case_05_name_typo` | name-correction, spelling fix | `policy_copy` (name misspelt), `rc` (correct), `pan` (correct) |
| `case_06_wrong_docs` | triage / adversarial | `unrelated_doc` (utility bill, blank page, or a selfie-style photo), `rc_rotated`, `duplicate_of_pan` (same PAN uploaded twice, second slightly different crop) |

Spread the three fictional insurers across the cases (**Northwind General**, **Cedar Mutual**, **Halcyon Assurance**). Case 01 and 04 → Northwind, 02 and 05 → Cedar, 03 and 06 → Halcyon.

## Tweaking rules

1. **Persona first.** Fill `personas.yaml` for the case before touching an image. Every value you type into a document comes from there, so the documents stay consistent with each other.
2. **Replace every identifying field**: names, relative's name (S/O, W/O), addresses, phone numbers, emails, dates of birth, policy numbers, registration numbers, chassis and engine numbers, Aadhaar and PAN numbers, signatures, customer ids, barcodes.
3. **Keep formats valid but unreal.** Registration numbers in the real pattern (`KA01AB1234`) but not a plausible live vehicle; PAN as `AAAAA9999A` with a made-up value; Aadhaar as 12 digits that you invent. Never keep a real prefix-plus-suffix combination. Dates move together: keep the same gaps between issue, expiry and transfer dates as the original.
4. **Photos and QR codes**: replace face photos with a neutral silhouette or a generated avatar. Blank out QR codes and barcodes, or replace them with a generated dummy QR that encodes nothing real.
5. **Insurer branding**: swap real insurer names, logos and URLs for one of the three fictional insurers. Do not leave a real logo anywhere, including watermarks and footers.
6. **Keep the layout, fonts and quirks** (stamps, folds, slight skew, small print). Realism is the point. Avoid clean, perfectly typeset results.
7. **Flatten and strip.** Export as a flattened PNG or JPG, never a PDF with a text layer (the original text lives in it). Strip metadata: `exiftool -all= file.png`.
8. **Degraded variants** are made from the clean file *after* tweaking (blur, crop, rotate), not from the original.
9. **Never commit originals**, screenshots of the editing process, or the `private_docs/` folder. If in doubt, leave the file out.

## After tweaking

Run the extractor over each case once. We compare its output with `personas.yaml`, correct either side, and save the agreed values as `expected.json` in each case folder. Those values are the ground truth for the extraction and scenario evals.

Minimum viable set to start: cases 01, 03 and 05. Add the rest as you find documents.
