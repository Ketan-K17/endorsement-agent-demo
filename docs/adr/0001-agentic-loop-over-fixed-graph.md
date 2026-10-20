# ADR-0001: Agentic tool loop over a fixed graph

Status: accepted

**Context.** The production agents are deterministic LangGraph workflows. The demo should showcase agent-architecture features (skills, status bar, evals).

**Decision.** One LangGraph agent node + tool node. The model chooses tools and order; the Case File holds state; code enforces budgets and gates (approval before submission, ask budget, idempotency).

**Consequences.** Behaviour varies run to run, so evals assert outcomes and invariants and run each scenario k times (pass^k). No hard-coded flow to unit-test; guardrails must live in tools, not prompts.
