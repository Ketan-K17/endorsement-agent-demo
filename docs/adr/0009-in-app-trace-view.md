# ADR-0009: In-app trace view; Langfuse stays private

Status: accepted

**Decision.** Visitors get an in-app trace view (tool calls, timings, token counts) built from the event stream. Langfuse uses a personal cloud project and its links are shown to the owner only.

**Why.** Visitors cannot open a private Langfuse project, so a `trace_url` would 404 or demand a login.
