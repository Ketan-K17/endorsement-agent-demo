# ADR-0002: Skill catalog lives in the `load_skill` tool definition

Status: accepted (proposed by assistant, pending user review)

**Context.** The system prompt is reserved for role, basic guidelines and the full SOP. Skills need a catalog the model can see before loading any. Options: (a) system prompt, (b) `load_skill` tool definition, (c) the status bar.

**Decision.** (b). The tool description lists each skill's name and "use when…" line, and `name` is an enum. Generated from `SKILL.md` frontmatter at startup.

**Why.** It is in the static prefix (cached), colocated with the tool that consumes it, keeps the system prompt clean, and the enum prevents hallucinated skill names. (c) would bloat the per-call tail and defeat caching.

**Consequences.** Adding a skill changes the tool schema, which invalidates the prefix cache once per deploy. Descriptions must stay one line.
