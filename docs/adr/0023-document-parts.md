# ADR-0023: Documents that come in parts

Status: accepted (by the user, 2026-11-07)

**Context.** An Aadhaar card has a front and a back; a policy copy has two pages. In case-a9ea568b the agent accepted the front of an Aadhaar alone, because nothing in the rules, skills or code knew a document has parts. The change-of-owner rows said "front and back" in a `note`, which is guidance only and was not followed reliably.

**Decision.** Parts are enforced in code, per document type, for every endorsement type and insurer.

- The rules master has `doc_parts`: `aadhaar: [front, back]`, `policy_copy: [page_1, page_2]`. Every requirement of that type carries its `parts`; `get_endorsement_rules` returns `doc_parts` so the agent can ask for all parts up front.
- `classify_document` also returns `parts`: which parts the image shows. One image can show several (a print with both sides). Parts not listed for the type are dropped.
- A required document is `accepted` in the checklist only when its accepted uploads together cover every part. Until then it is `partial`, with the reason `needs <part>`, and the stage stays at Docs, so `validate_case` fails on it. The `extract_fields` result names the part still needed.
- Each part is its own upload and its own document in the Case File. There is no merging.

**Consequences.** The classifier must tell front from back and page 1 from page 2; a wrong or empty `parts` leaves the document `partial`, and the agent asks again rather than letting it through. `tools/extract_fixtures.py` checks `parts` against `expected.json`. The notes that said "front and back" now just name whose document it is.
