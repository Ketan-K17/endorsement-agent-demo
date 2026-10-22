# ADR-0011: Existing Azure credentials for now, with hard usage caps

Status: accepted (user, 2026-10-22); subject to change

**Decision.** The demo uses an existing Azure OpenAI resource for now; Langfuse is a personal cloud project. Usage is heavily limited: 60 model calls and 150k tokens per session, 3 sessions per IP per day, a global daily budget switch, an optional invite code, and a pre-recorded run as the fallback when a cap trips.

**Consequences.** Moving to personal keys is an env-var change because models are configured per role (ADR-0007). Secrets are never committed.
