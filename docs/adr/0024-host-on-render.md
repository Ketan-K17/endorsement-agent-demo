# ADR-0024: Host on Render, not Hugging Face Spaces

Status: accepted (by the user, 2026-11-07)

**Context.** DESIGN §11 chose Hugging Face Spaces (Docker) with Render free as the fallback. By 2026-11 the Docker SDK on Spaces is paid-only for this account (checked by the user when creating a Space).

**Decision.** Deploy to a Render free web service, built from a Dockerfile. One instance. SSE buffering disabled. The app reads its port from `PORT`.

**Consequences.** Render's free tier, per its docs as of 2026-11 (to re-verify at deploy time): the service spins down after 15 minutes with no inbound traffic, wakes in about a minute, and the workspace gets 750 free instance hours a month. Sessions live in memory (ADR-0018, ADR-0022), so a spin-down or redeploy loses every open case, as a restart already did. The cold start is shown to the visitor, not hidden. A paid instance removes the spin-down without code changes. Scaling past one instance would break in-memory sessions and is out of scope.
