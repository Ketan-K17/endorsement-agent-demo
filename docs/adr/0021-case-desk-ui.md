# ADR-0021: Case Desk UI

Status: accepted (by the user, 2026-11-07, from a static mockup)

**Context.** The UI (ADR-0018) worked but looked like a generic admin page, at odds with the playful intro. Tool activity lived in a side feed, apart from the conversation it belonged to, and the Context tab's green/red read as pass/fail rather than "still in the prompt / left it".

**Decision.** One visual language, a paper-and-ink claims desk, in a single light theme. Static HTML/CSS/JS as before; fonts from Google Fonts with system fallbacks.

- **Three panes.** Left, a **flight recorder** replaces the Activity feed: one uniform row per step (time, dot, step, optional detail). Routine tool calls in the same model step fold into one row; changes (`record_slot`, `record_change_request`, `waive_requirement`, `validate_case`) get their own row; turning points (`ask_user`, `request_approval`, `handover`, `submit_to_insurer`, refused calls, approval decisions) get a red dot. Centre, the conversation. Right, the case file.
- **The conversation is one ruled pad.** The customer writes by hand, the agent types, and each model step's tool calls appear inline as one foldable margin note. The approval card is a form drawn on the same sheet, decided with rubber stamps. The composer is the pad's next blank lines.
- **The document dock becomes an in-tray** of thumbnails under the pad.
- **Case file.** Status is a sticky note, the assignee a luggage tag. Recorded values show their source (`doc:<id>` as the file name, `user_msg` as "you"), taken from `slot.recorded` events the client already has; the approval form shows the same sources. No API change.
- **Trace** is a till receipt. **Context** items are flat envelopes coloured by kind; items that left the prompt fade, get a dashed edge and a stamp saying why (superseded, compressed, stubbed). This replaces DESIGN §14's green/red.
- Recorder and tool notes are rebuilt from the event stream (ADR-0008), so replay drives them too.

**Consequences.** The intro keeps its own styles through token aliases. Every element the old UI showed is still present; only its place and look changed. Typewriter text for long agent replies may prove tiring; if so, only the "Agent" label stays typewritten.
