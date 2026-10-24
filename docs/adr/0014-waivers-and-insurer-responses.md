# ADR-0014: Conditional requirements are waived; insurer queries are answered

Status: accepted (user, 2026-10-24)

**Context.** Rules carry free-text conditions ("only if the policy shows a financier") that the model must interpret, but nothing let it mark one as not applying, so a case would sit in Docs or force a pointless ask. After submission the mock insurer can raise a query, but nothing sent the answer back.

**Decision.**
- New tool `waive_requirement(name, reason)`. Code refuses a requirement without a condition. It emits `requirement.waived`; the checklist shows `waived (reason)`, and waived items count as satisfied for the stage and drop out of the slot total.
- New tool `respond_to_insurer(ref, message, doc_ids?)`. The mock insurer holds at `query_raised` until a response arrives; the next `check_insurer_status` then advances. Responses are kept for eval assertions.

**Consequences.** Two more tools in the catalog. Evals can assert that a waiver cites its condition and that every insurer query was answered before the case closed.
