# ADR-0017: The LLM pass of validate_case

Status: accepted (built at the user's request, 2026-11-06; the specifics proposed by the assistant)

**Context.** ADR-0015 left `validate_case` deterministic until real extractions existed. Fixed rules compare identifiers, but not names across documents, handover conditions written as free text, or impossible dates.

**Decision.**
- **Runs only after the deterministic checks pass**, so the blocking gaps come first and the model is called once per near-final case.
- **Judge role** (`gpt-5`): a different model from the agent checks the agent's work. No new role or config.
- **Input is facts, not the conversation:** policy, change request, stated values, fields of accepted documents, the insurer's `handover_if`, and today's date.
- **Carry-forward:** the previous `consistency:` issues are passed back, and the model repeats the wording of each that still holds. Issues are prefixed `consistency: ` and sorted, so `diff_vs_prev` stays stable on unchanged facts.
- **Fails closed:** if the call fails, the result is an issue, so approval cannot pass on a check that did not run.

**Consequences.** A passing validation costs one judge call (about 25 s on the live model). The verdict is no longer exactly reproducible; evals assert on the deterministic issues and treat `consistency:` issues by scenario. The eval judge and this check share a model, so a judge eval must not grade the check's own output.
