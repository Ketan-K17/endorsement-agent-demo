# ADR-0005: No RAG; the full SOP is in the system prompt

Status: accepted (user decision)

**Decision.** The whole SOP is part of the system prompt, alongside the role and basic guidelines. Specialised detail lives in skills and their reference files (`read_skill_file`). No retrieval tool or vector store unless the user explicitly asks.

**Consequences.** The SOP must stay compact enough for the context window and is cached as part of the static prefix. Citation of SOP sections is done by section id in the model's replies, checked by the LLM judge.
