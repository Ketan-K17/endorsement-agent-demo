# ADR-0019: Tool-call cap of 40, announced in the status bar

Status: accepted (by the user, 2026-11-07)

**Context.** In session case-d6399feb (case 05, name typo) the first turn made 20 tool calls by `validate_case`, with `MAX_TOOL_CALLS_PER_TURN=20`. The next model call was bound with `tool_choice="none"` (ADR-0015), so it could not call `request_approval`. Nothing told it why, and it replied "I'm unable to initiate approval right now". The trace showed the tool definitions (they stay bound for the cache) but not `tool_choice`, so it looked like a model slip. `evals/approval_after_pass.py` replays that turn: 0/5 at cap 20, 3/3 at 30. A plain endorsement can need 20+ calls in one turn, so the old default of 12 cut the happy path short.

**Decision.**
- **Default cap 40.** It still stops a runaway loop, but no longer one the normal path runs into.
- **A capped call is told so.** When the cap is reached, the status bar for that call gets one more line: `turn: tool-call cap reached (N/N); no tools until the user's next message. Say what you will do next; it continues when they reply.` The loop adds it in `model_input`; `render_status` stays a pure function of the Case File and the date, and the line is never stored, like the rest of the bar.

**Consequences.** A capped turn now ends with an honest reply ("I'll request approval when you reply") instead of an invented reason. The cap still costs the user a message when it is hit; that is the price of the guard. The regression eval passes at the default cap.
