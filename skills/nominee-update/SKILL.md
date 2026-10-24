---
name: nominee-update
description: Use when the policyholder wants to add, change or remove the nominee.
tools_hint: [get_endorsement_rules, classify_document, extract_fields, record_slot]
---
# Nominee update

Workflow
1. Rules for `nominee-update` and the policy's insurer.
2. Values: new nominee's name, relationship, date of birth (ask only what the rules list).
3. Collect the documents the rules list (often the nominee's ID).

Fields to extract
- nominee_id: name, dob
- policy_copy: policy_no, reg_no, holder_name

Checks
- Nominee ID name = stated nominee name.
- A minor nominee needs an appointee; ask for the appointee's name if the rules list it.
- The policyholder cannot be their own nominee.
