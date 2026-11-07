---
name: document-triage
description: Use when uploads are unclear, of the wrong type, or more than one arrives at once.
tools_hint: [list_documents, classify_document, extract_fields]
---
# Document triage

- Classify every new upload in parallel, then extract in parallel.
- A document in parts (Aadhaar front/back, policy copy pages) stays `partial` until every part is accepted; ask for the missing part by name.
- Wrong type: say what it looks like and what is still needed. Never relabel it.
- Poor or unreadable: name the problem (blur, glare, cropped) and ask for one clearer copy.
- Never record ID numbers (Aadhaar, PAN) as values; names and dates only.
- A value read below 0.7 confidence: confirm it with the user in the next ask, don't guess.
