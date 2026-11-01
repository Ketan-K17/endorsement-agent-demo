# Handover: fixture documents for step 4

What you need to produce before step 4 (extraction) can be finished, and where the rules already live. This file collects them; it doesn't replace them.

## Read these (they already exist)

| File | What it settles |
|---|---|
| `fixtures/documents/README.md` | Folder per case, exact filenames, insurer per case, **the 9 tweaking rules**, the `expected.json` step |
| `fixtures/documents/personas.yaml` | The invented values every document must show |
| `src/endorsement_agent/mock_world/data/policies.yaml` | Policy master. Its first five entries are cases 01–05 and carry values personas don't (chassis, engine, vehicle, nominee, phone). `tests/test_mock_world.py` fails if it drifts from personas |
| `src/endorsement_agent/mock_world/data/rules.yaml` | Which docs each insurer requires per endorsement type, and the doc-type names the classifier uses |
| `DESIGN.md` §12 | Real docs stay in `private_docs/`; ground truth is `expected.json` |
| `docs/adr/0006-interactive-approval-and-private-test-docs.md` | Why real docs never enter git |
| `docs/PROJECT_CONTEXT.md` (risks) | Residual re-identification risk; **you** do the final check before anything is committed |

## Workflow per case

1. Pick an original from your stash, copy it into `private_docs/<case>/` (untracked).
2. Take every value from `personas.yaml`; anything personas lack, take from `policies.yaml`; anything both lack, invent it and **add it to `personas.yaml`** (see gaps below).
3. Tweak per the README rules: replace all identifiers, silhouette the photos, blank QR codes and barcodes, swap the insurer branding, keep the layout and quirks.
4. Export a flattened PNG/JPG and strip the metadata (`exiftool -all= file.png`).
5. Make degraded variants (blur, crop, rotate) from the **tweaked** file, never from the original.
6. Drop the finished files into `fixtures/documents/<case>/` with the exact filenames from the README.
7. Tell me. I run the extractor, we reconcile against personas, and I write `expected.json`.

## Documents needed, by priority

**Start with cases 01, 03, 05** (14 files). Cases 02, 04, 06 can follow before step 6 (evals).

| Case | Insurer | Files | Persona source |
|---|---|---|---|
| 01 owner transfer, clean | Northwind General | `policy_copy`, `rc_old_owner`, `rc_new_owner`, `aadhaar_front`, `aadhaar_back`, `pan`, `transfer_form` | personas + policy (nominee Sunanda Kulkarni, spouse, 58, prints on the policy copy) |
| 03 nominee update | Halcyon Assurance | `policy_copy`, `aadhaar_front`, `aadhaar_back`, `nominee_id` (optional) | personas + policy (Toyota Glanza, chassis/engine) |
| 05 name typo | Cedar Mutual | `policy_copy` (name **Jignesh Pattel**), `rc` (**Jignesh Patel**), `pan` (**Jignesh Patel**) | personas + policy (Mahindra XUV300, address, phone) |
| 02 owner transfer, degraded | Cedar Mutual | as case 01 but `rc_new_owner` blurry, `pan` cropped, **no** `transfer_form` | personas + policy |
| 04 name change by marriage | Northwind General | `policy_copy` + `rc` (Priya Hegde), `aadhaar_front` + `aadhaar_back` (Priya Kamath), `name_change_proof` (marriage certificate) | personas + policy (Tata Tiago, phone) |
| 06 wrong docs | Halcyon Assurance | `unrelated_doc`, `rc_rotated`, `duplicate_of_pan` | reuses case 03's persona |

## Gaps to fill in `personas.yaml` as you go

Documents print values the personas don't have. Invent them and add them to the case entry, so `expected.json` has one source:

- **Aadhaar (all cases):** gender, and a DOB where missing (cases 03 and 04 have none; case 04 has no DOB at all).
- **PAN (cases 01, 02, 05):** father's name and DOB. Case 05 has neither. Cases 01 and 02 can reuse `relative_name` and `dob`.
- **RC (cases 01, 02, 04, 05):** registration date, RTO, colour, maker's class.
- **Policy copy (all):** premium, IDV, previous insurer if shown. Keep the period from `policies.yaml`.
- **Case 04:** marriage date, spouse name, certificate number for `name_change_proof`.
- **Case 06 needs documents case 03 never asks for:** `rc_rotated` is an RC in Lakshmi Narayanan's name (TN09KV2261), and `duplicate_of_pan` needs a PAN for her. Add `pan_no` (and the PAN fields) to case 03. If you also produce a clean `rc` for case 03, drop it in case 03's folder as an extra.

## Things I'll handle (no action from you)

- **Case 01's transfer date is now more than 14 days ago.** `transfer_date` 2026-10-09 is 15 days before today (2026-10-24). Northwind's rule then asks for an `inspection_report`, so the "clean" path is no longer clean on live runs. Step 6 evals will pin `today`. For live demos I'll propose moving the date or pinning the clock in an ADR. You don't need an inspection report.
- Case 01 includes a `pan` that Northwind doesn't require. Keep it: an extra document the agent should classify and leave unused is a useful check.

## Before you hand files over: final check (yours)

- [ ] No real name, number, address, signature, face, QR code or barcode is left, including stamps, watermarks and small print
- [ ] No real insurer name or logo anywhere
- [ ] Flattened PNG/JPG, metadata stripped (`exiftool -a file.png` shows nothing personal)
- [ ] Values match `personas.yaml` (and `policies.yaml`) for that case
- [ ] Nothing from `private_docs/` or any editing screenshots staged (`git status` before commit)

## Is this blocking step 4?

Partly. Without documents I can build and unit-test the vision adapter (classify and extract on the extractor role), the extraction prompt and schema, and the deterministic hooks, all against fakes. Finishing step 4 needs the documents: the live check, `expected.json`, and the LLM pass of `validate_case` (ADR-0015 deferred it until real extractions exist).
