---
name: name-correction
description: Use when the policyholder's name is misspelt or changed (e.g. after marriage).
tools_hint: [get_endorsement_rules, classify_document, extract_fields, cross_check]
---
# Name correction

Two cases
- Typo: one or two letters differ. ID proof with the correct name is enough.
- Change: a different name (marriage, gazette). Needs proof linking old and new name.

Fields to extract
- aadhaar / pan: name
- rc: owner_name, reg_no
- name_change_proof: old_name, new_name

Checks
- `cross_check` policy.holder_name against the ID name: partial suggests a typo or added surname.
- Proof old_name = policy name; new_name = the ID name.
- New name shares nothing with the old one and there is no proof → hand over.
