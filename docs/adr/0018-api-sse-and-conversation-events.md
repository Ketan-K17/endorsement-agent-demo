# ADR-0018: API, SSE stream and conversation events

Status: proposed (build step 5)

**Context.** The UI needs a live chat, activity feed, trace view, replay and Context tab (DESIGN §14), all from one event stream (ADR-0008). Until now the stream held Case File events only; messages, model calls and tool timings were not in it.

**Decision.**
- **Conversation events join the case stream:** `message.user`, `message.assistant`, `model.called` (duration, tokens, `n_messages`), `tool.called` (args; its `tool.result` gives the timing). The fold ignores them. `tool.called` is not re-emitted when a call re-runs on resume after approval.
- **One SSE stream per session** (`GET /api/sessions/{id}/stream`, plain `EventSource`): every case event (`event`, id = seq, so a reconnect resumes after `Last-Event-ID`), agent text deltas (`token`, never stored), the UI status bar (`status`) after each tool result and at the end of each turn, `turn` (reply or approval card) and `agent_error`. The event store gets a per-case listener; there is no polling.
- **Turns run as background tasks.** `POST …/messages` and `POST …/approval` return 202; one turn at a time per session (409 otherwise, and while an approval is pending).
- **Uploads are JSON with base64 images** (PNG/JPEG, 8 MB each), so no multipart dependency.
- **Context tab is fetched, not animated** (`GET …/context`, allowed by DESIGN §14). Each past status bar is rebuilt by folding the events before its `model.called` and placed after the `n_messages` it followed; nothing about it is stored (ADR-0003).
- `current_activity` and `trace_view` (totals from events) are added to the UI bar by the API layer (ADR-0013).
- Sessions live in memory with no eviction. Usage limits, invite code and the pre-recorded fallback come with the deploy step (DESIGN §17, step 7).

**Consequences.** Replay is the client playing back the events it already has. Evals can assert on model and tool calls from the same stream. Session memory grows until restart, acceptable until step 7 adds caps.
