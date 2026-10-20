# ADR-0007: Model per role on Azure OpenAI

Status: accepted (user, 2026-10-20)

**Decision.** Role-based LLM interface with config per role:
- agent: `gpt-5.6-sol` (India resource)
- extractor (vision): `gpt-5.4-mini` (US resource)
- compressor: `gpt-5.4-nano` (US resource)
- judge: `gpt-5` (US resource), deliberately a different model from the agent

**Why.** Probed 2026-10-20: all four pass chat, tool calling, image input and strict JSON schema. No 5.5-family deployment exists on either resource. `gpt-5.6-sol` was the fastest in the probe.

**Consequences.** Two endpoint/key configs. Credentials are read from env, never committed. Revisit after the first eval runs.
