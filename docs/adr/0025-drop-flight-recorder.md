# ADR-0025: Drop the flight recorder; the agent's line says what it is up to

Status: accepted (by the user, 2026-11-07)

**Context.** The flight recorder (ADR-0021) listed every step in a left pane. The Trace tab lists the same steps with timings, and each model step's tool calls already sit in the chat as margin notes, so the pane said things twice and squeezed the pad. Meanwhile, after the user sent a message the pad showed nothing until the first margin note or token, so it looked stuck.

**Decision.**

- Remove the flight recorder. The layout is two panes, the pad and the case file, with more room between elements. Margin notes and the Trace tab carry the step list.
- While a turn runs and before the agent writes, the pad shows an **Agent placeholder**: one line that cycles through whimsical desk phrases ("Licking stamps…"), with the status bar's `current_activity` beside it. The turn's margin notes land underneath it.
- It appears on a live `message.user` or `approval.decided`, or on a busy status (a reload mid-turn). It goes on the first reply token, `message.assistant`, the turn end, an `agent_error`, or an idle status. Replay never shows it. Client-only; no API change.

**Consequences.** One less view of the event stream to keep in step (ADR-0008 still feeds the chat, trace and context). The phrases are decoration, not information; the activity text next to them is the real signal.
