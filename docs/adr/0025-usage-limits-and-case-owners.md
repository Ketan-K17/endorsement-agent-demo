# ADR-0025: Usage limits and case owners

Status: accepted (by the user, 2026-11-07); token counting amended by ADR-0026 (cache reads excluded)

**Context.** ADR-0011 set the limits for the public demo, which runs on the user's existing Azure keys; the user allows that only with these limits in place. None were enforced. Token counts were recorded for agent calls only, not for the extractor, compressor or judge. ADR-0022 left cases open to anyone holding an id, with memory growing without bound.

**Decision.**

- **Per case:** `SESSION_MAX_MODEL_CALLS` counts agent calls (`model.called` events), the guard against a runaway loop. `SESSION_MAX_TOKENS` counts input plus output tokens on all four roles, through a callback attached to each of the case's models.
- **Per day** (the Asia/Kolkata calendar day, never `FIXED_TODAY`): `DAILY_MAX_TOKENS` (new) caps tokens across all cases. `DAILY_BUDGET_SWITCH=off` closes the demo by hand. `IP_MAX_SESSIONS_PER_DAY` counts the cases an IP sends a first message in, not the cases it opens: a bare `/` opens a case on every load.
- **Where a cap bites:** before each agent call. A spent case or day ends the turn with a fixed assistant message and no model call, so the turn still ends on a plain reply (ADR-0010). Calls already in flight finish, so a case can overshoot by one step. A new message to a spent case is refused with 429. A pending approval can still be decided; the turn after it ends on the same fixed message.
- **Invite code:** when `INVITE_CODE` is set, opening a case needs it in `X-Invite-Code`. The page asks once and keeps it in `localStorage`.
- **Owners:** opening a case sets an `owner` cookie (random, HttpOnly, SameSite=Lax) if the browser has none. Every `/api/sessions/{id}` route needs the case's owner cookie, else 404. A `?case=` link works only in the browser that opened it.
- **Memory:** at most 40 cases live. A case with no turn running and no open stream is dropped 2 hours after its last activity. Opening a case past the cap is refused with 503.
- **Counters live in memory.** A restart or a Render spin-down resets the day's counts. Accepted by the user: each case stays capped, and there is no ceiling outside the app.

**Consequences.** The client IP is `request.client.host`. Behind Render's proxy it is only the visitor's address once uvicorn trusts the proxy's forwarded headers, and the cookie gets `Secure` only when the request is seen as https. Both are deploy configuration (step 7); the IP is settled by ADR-0027 (a configured header, not `X-Forwarded-For`). The pre-recorded run offered when a cap trips is deferred until curated runs exist. The terminal smoke run (`python -m endorsement_agent`) has no limits. The per-case token cap is sized in ADR-0026 (100k).
