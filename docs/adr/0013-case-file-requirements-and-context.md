# ADR-0013: Requirements and context meter live in the Case File

Status: accepted (user, 2026-10-24)

**Context.** `render_status(case)` must be a pure function of the Case File (ADR-0003), but the status bar needs what the case requires (docs checklist, slot totals, the Docs stage) and the context meter, neither of which DESIGN §3 held.

**Decision.**
- `requirements: {docs: [{name, condition?}], slots: [{name, condition?}]}` is set by a `rules.loaded` event when `get_endorsement_rules` runs. Until then the stage is Docs.
- `context: {uncompressed_tool_results, threshold, last_compressed_at}` is folded from `tool.result` (excluding `ask_user`) and `context.compressed` events.
- `case.created` carries `ask_budget` and `compress_threshold`, so the bar and replay need no config.
- Slots hold the current value only, with `supersede_reason`; earlier values stay in the event log (replaces `superseded_by`).
- A doc's verdict is set by a `document.reviewed` event; the fold applies events and enforces no gates.
- `current_activity` and `trace_view` are not Case File state; the API layer adds them to the UI bar.

**Consequences.** One stream and one fold still drive everything (ADR-0008). Conditional requirements are listed with their free-text condition; how one is waived is decided with the rules master in step 2.
