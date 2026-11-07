# ADR-0020: Agent Documentation tab for tools and skills

Status: proposed

The tab is shown full width: the status and activity panels and the document dock are hidden while it is open.

**Context.** The Activity feed, Trace and Context tabs show tool names (`record_slot`, `load_skill`...) that mean nothing to a visitor. Tool descriptions are written for the model, not people.

**Decision.**
- A fourth tab, **Agent Documentation**, documents every tool and skill. `GET /api/reference` builds it from the live registries: tool names, model-facing descriptions and argument tables from `TOOLS`; skill catalog, full text and reference files from `skills/`. Only the plain-language prose (summary, when used, guardrails, grouping) is hand-written, in `tool_docs.yaml`.
- `tests/test_reference.py` fails if a tool has no entry or an entry has no tool, so the page cannot drift from the code. Skills need no extra file.
- Every tool and skill name in the Activity feed, Trace rows and Context items links to `#/ref/tool/<name>` or `#/ref/skill/<name>`. The hash is a stable deep link; loading it opens the tab and highlights the entry. `load_skill` / `read_skill_file` calls also link the skill they touched.
- Not routable: model calls, compression and image-stub rows, which are not tools.

**Consequences.** Adding a tool means one yaml entry. The Agent Documentation tab sits beside the session views but needs no session. No new dependency.
