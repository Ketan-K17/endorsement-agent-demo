# CLAUDE.md — endorsement-agent

Portfolio demo of an agentic insurance-endorsement assistant. Performative, not production: it exists to show agent-architecture ideas (skills, derived status bar, context compression, approval gate, evals). All data is synthetic or tweaked.

**Read first, in order:** `docs/PROJECT_CONTEXT.md` → `DESIGN.md` → `docs/adr/` → `GLOSSARY.md`. Check "Build status" below before starting work.

## Working rules

- **Think first.** Read the files a task touches before editing. If the code or docs don't match what you expected, stop and ask.
- **Simple and surgical.** Smallest diff that works. No speculative abstraction, no new tool/service/config the design doesn't list.
- **Design is settled; code follows it.** If the design seems wrong, say so and propose an ADR; don't silently deviate. Record any new decision as an ADR in `docs/adr/`.
- **One build step at a time** (see `DESIGN.md` §17). Each step runnable and tested before the next. Don't start a step the user hasn't approved.
- **No RAG** unless the user explicitly asks. Knowledge is the system prompt (SOP) or skills.
- **No restore/expand tool** for compressed tool results (rejected, ADR-0004).

## Hard constraints (public repo)

- Nothing proprietary: no text, prompts, node structure, rule rows or identifiers copied from any employer system. The production rulebook only inspired the *shape* of the mock rules master. Write all SOP, skill and rule content fresh, terse, from public knowledge.
- Insurers are fictional: Northwind General, Cedar Mutual, Halcyon Assurance.
- Real documents never enter git. They live in untracked `private_docs/`. Only tweaked files go in `fixtures/documents/` (see its README).
- No secrets in git. Credentials come from `.env` (gitignored); `.env.example` lists names only. Never print key values in logs, output or traces.
- No PII in logs or traces beyond what the fixtures contain (which are tweaked).

## Stack and conventions

- Python 3.12, `uv` for deps, `src/endorsement_agent/` layout, tests in `tests/`.
- LangGraph for the loop (agent node + tool node, checkpointer, `interrupt()` for approval). Azure OpenAI via a role-based client (agent / extractor / compressor / judge), config per role from env. FastAPI + SSE backend. Static HTML/CSS/JS frontend, no build step. Langfuse cloud (personal project) for tracing.
- Type hints on all public functions; Pydantic v2 models for the Case File, events, tool args and status bar. `from __future__ import annotations`.
- No bare `except`. No `print()` in library code; use `logging`.
- Async where I/O happens (LLM, SSE); pure functions (reducers, `render_status`) stay sync and side-effect free.
- Tests: `uv run pytest`. Lint/type: `uv run ruff check . && uv run mypy src`.
- Snapshot tests for `render_status`; scenario evals under `evals/`. Never call a real LLM in unit tests.
- Commits: conventional (`feat(core): …`). Add attribution lines per the harness reminder.

## Key design invariants (do not break)

1. Prompt order: system prompt (role + guidelines + full SOP) → tool definitions → full history → status bar last.
2. Status bar is a pure function of the Case File, built per model call, **never persisted** in history or checkpoints.
3. History is never truncated; only image stubbing and tool-result compression transform it, both recorded in the event log with originals kept.
4. Compression: trigger at 5 uncompressed tool results, compress all but the most recent, never recount or recompress, parallel results count individually, `ask_user` acks excluded.
5. Slots are written only through `record_slot`. `submit_to_insurer` is code-enforced to require an approved approval.
6. A turn ends on a plain assistant message with no tool call. There is no `send_reply`.
7. Case File is event-sourced; one event stream feeds UI, replay, traces and evals.

## Environment variables

Names only; values in `.env` (see `.env.example`). Per role `<ROLE>` ∈ `AGENT`, `EXTRACTOR`, `COMPRESSOR`, `JUDGE`: `<ROLE>_ENDPOINT`, `<ROLE>_API_KEY`, `<ROLE>_DEPLOYMENT`, `<ROLE>_API_VERSION`. Plus `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `COMPRESS_THRESHOLD`, `ASK_BUDGET`, `MAX_TOOL_CALLS_PER_TURN`, `SESSION_MAX_MODEL_CALLS`, `SESSION_MAX_TOKENS`, `IP_MAX_SESSIONS_PER_DAY`, `DAILY_BUDGET_SWITCH`, `INVITE_CODE`.

Model assignment (ADR-0007): agent `gpt-5.6-sol` (India resource); extractor `gpt-5.4-mini`, compressor `gpt-5.4-nano`, judge `gpt-5` (US resource). Check availability and capabilities with `tools/probe_models.py`.

## Build status

Update this block when a step finishes.

- [x] Design, glossary, ADRs 0001–0012, fixture folders
- [ ] 1. Case File, event store, `render_status` + snapshot tests  ← next
- [ ] 2. Mock world: policies, rules master, insurer state machine
- [ ] 3. Tools + LangGraph loop + status bar + image stubbing + compression
- [ ] 4. Extraction against fixture documents (needs tweaked docs from the user)
- [ ] 5. API + SSE + UI
- [ ] 6. Evals + nightly runs
- [ ] 7. Deploy to Hugging Face Spaces with limits (needs credentials sign-off)

## Waiting on the user

- Tweaked documents per `fixtures/documents/README.md` (start with cases 01, 03, 05) and `personas.yaml`.
- Personal Langfuse project credentials (needed from step 3).
- `.env` with Azure credentials for the roles above.
