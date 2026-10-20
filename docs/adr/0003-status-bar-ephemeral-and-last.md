# ADR-0003: Status bar is ephemeral and always the last block

Status: accepted

**Decision.** `render_status(case)` is rendered on every model call and appended after the chat history. It is never written to stored history or the checkpointer. The same function feeds the UI over SSE.

**Why.** Guarantees the model never sees stale copies; keeps the bar a pure function of the Case File (not LLM-generated); keeps everything above it append-only so the prefix cache stays warm.

**Consequences.** The bar's token cost is paid on every call, so it stays compact. The UI bar and the model bar share one renderer, tested with snapshot tests.
