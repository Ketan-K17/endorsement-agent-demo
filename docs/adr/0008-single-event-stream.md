# ADR-0008: One event stream for UI, replay, traces and evals

Status: accepted

**Decision.** A single event schema (append-only) drives the live feed, status bar, Context tab, session replay, Langfuse trace and eval assertions. Replay is the session's events played back.

**Consequences.** No separate recording system. Replay of a user's own run works while the session lives; curated example runs are committed as static event logs; shareable links for user sessions are dropped because the Space disk is ephemeral.
