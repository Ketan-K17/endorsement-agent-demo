---
name: change-of-owner
description: Use when the vehicle was sold and the policy must move to the new owner.
tools_hint: [get_endorsement_rules, classify_document, extract_fields, cross_check, waive_requirement]
---
# Change of owner

The policy moves from the seller (current policyholder) to the buyer.

Workflow
1. Rules for `change-of-owner` and the policy's insurer.
2. Waive conditional items the policy facts settle (e.g. no financier on the policy → no NOC).
3. Collect: RC in the new owner's name, transfer form, new owner's ID, plus what the rules add.
4. Values: new_owner_name, new_owner_phone, transfer_date.

Fields to extract
- rc: reg_no, owner_name, chassis_no, engine_no, hypothecated_to
- transfer_form: reg_no, seller_name, buyer_name, transfer_date
- aadhaar / pan: name
- noc: financier, reg_no, addressed_to

Checks
- RC reg_no = policy reg_no. RC owner_name = new_owner_name.
- Transfer form seller_name = policyholder; buyer_name = new_owner_name.
- Seller is not the policyholder → hand over.

References
- `transfer-form.md` — read when the transfer form is unclear or a plain letter is offered.
