# ADR-0004: Tool-result compression (proof of concept)

Status: accepted

**Context.** Full history is kept (no truncation). Tool results (extractions, policy lookups, rule dumps) are the bulkiest, lowest-reuse content. The goal is a visible, correct PoC of context compression, not token savings.

**Decision.**
- Compress only tool results; never user/assistant messages (which include the tool calls).
- Trigger when uncompressed tool results reach 5 (configurable). Compress all of them except the most recent. Already-compressed results are not counted again and not recompressed.
- Compressor = small model with per-tool prompts; near-lossless: drop wording and boilerplate, keep every identifier, value, confidence, decision and error state.
- Originals stay in the event log for audit and evals. There is no tool for the model to restore them (rejected as unnecessary complexity).
- Emit `context.compressed` events to the trace, UI timeline and status-bar context meter.

**Why batch.** Per-turn compression would rewrite the prefix every call and defeat caching; batching changes it only at compression events.

**Consequences.** Needs dedicated evals: needle-after-compression, outcome parity on/off, compressor fidelity. A lossy stub can cause the agent to act on missing detail; mitigations are the near-lossless compressor prompt and the Case File as source of truth.
