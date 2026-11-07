# ADR-0022: Revisit cases within a sitting, and survive a reload

Status: accepted (by the user, 2026-11-07)

**Context.** A visitor may run several cases in one sitting and want to go back to an earlier one, or simply reload the page. The server already keeps every session in memory and its stream replays the full event log from `seq` 0 (ADR-0008, ADR-0018), but the page forgot its case id on reload and "New case" was the only way forward.

**Decision.** No server-side persistence. Within one server process:

- The current case id is in the URL as `?case=<id>`, set with `history.replaceState`. A reload or a pasted link re-attaches; the replayed log rebuilds chat, recorder, case file and any pending approval card. A bare `/` starts a new case. The query string, not the hash, so it does not clash with `#/ref/...` deep links (ADR-0020).
- `GET /api/sessions/{id}` returns `{session_id, busy}` or 404, so the page can check a remembered case before attaching.
- The browser keeps its last 12 case ids in `localStorage` (id, policy number once known, which demo in-tray it used), shown as a picker in the header. Entries the server no longer knows are dropped on load and on a failed switch. There is no server endpoint that lists cases.
- An unknown `?case=` shows a notice and opens a new case; it is never silently replaced.
- The first `status` message after connecting ends the replayed backlog. A submission seen before it is not celebrated again. Dock "sent" marks are rebuilt from `document.uploaded` events.

**Consequences.** A server restart (including `uvicorn --reload` on a code edit) loses every case. A reload drops unsent composer text and attachments, and token text streamed before it during a running turn; the final assistant message fills that in. A reload mid-POST may or may not deliver the message; the replayed log shows which. Anyone holding a case id can open it, and memory grows without bound: before the public deploy (step 7) sessions need an owner token and a cap or TTL.
