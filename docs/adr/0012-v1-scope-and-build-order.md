# ADR-0012: v1 scope and build order

Status: accepted

**Scope.** Skills: `change-of-owner`, `nominee-update`, `name-correction` (terse). Evals: component evals on the fixture documents, ~12 scenarios, compression evals, invariants always; k=3 nightly, k=1 on PR. Deferred to v1.1: judge calibration, prompt-injection and fault-injection suites.

**Order.** Core state and status bar → mock world → tools and loop → extraction → API and UI → evals → deploy. Each step runnable and tested before the next.
