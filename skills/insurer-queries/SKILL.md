---
name: insurer-queries
description: Use when the insurer raises a query or rejects a submitted case.
tools_hint: [check_insurer_status, ask_user, respond_to_insurer, handover]
---
# Insurer queries

- Relay the query in plain words; say exactly what the insurer needs.
- The answer is a document: process it like any upload, then pass its doc id to `respond_to_insurer`.
- The answer is a fact: record it, then respond with it.
- After responding, check the status once more and report.
- Rejection: explain the reason; hand over unless the fix is a simple re-upload.
