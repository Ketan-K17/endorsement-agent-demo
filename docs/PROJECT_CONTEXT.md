# Project context

Why this exists, what was decided, and what a new contributor (human or agent) must not get wrong. Read this before `DESIGN.md`.

## Origin and goal

The owner maintains production agents for insurance operations (endorsements, claims, payouts) built as deterministic multi-node workflows. This repo rebuilds the **endorsement** agent from scratch as a public portfolio demo, with mocked data, to showcase agent-architecture features: a tool-using (non-deterministic) loop, a skill catalog with progressive disclosure, a derived live status bar, near-lossless tool-result compression, a human approval gate, and an eval harness.

The goal is to be **performative, not useful in production**. Most viewers will see the README (with a GIF of one full flow) and the eval results table before, or instead of, trying the live demo. Rank: README/GIF, eval table, live demo.

## What an endorsement is

A change to an existing motor policy: change of owner, nominee update, name correction, etc. The customer asks, the agent works out the type and insurer, fetches the required documents and conditions, collects them, validates, asks a human approver, submits to the insurer, and tracks the insurer's response. In the demo the visitor plays both customer and approver.

## Decisions at a glance (details in ADRs and `DESIGN.md`)

- Agentic tool loop over a fixed graph (0001). Case File holds state; code enforces gates.
- Skill catalog lives in the `load_skill` tool definition (0002). Skills have `SKILL.md` + `references/`, fetched with `read_skill_file`.
- Status bar: pure function of state, appended last, never stored (0003).
- Tool-result compression, near-lossless, no restore tool (0004).
- No RAG; full SOP in the system prompt (0005).
- Interactive approval; real documents stay out of git (0006).
- Model per role on Azure OpenAI (0007). No 5.5-family deployment exists; `gpt-5.6-sol` is the agent.
- One event stream for UI, replay, traces and evals (0008). In-app trace view; Langfuse private (0009).
- Plain assistant message ends a turn; no `send_reply` (0010).
- Usage caps and credentials (0011). Scope and build order (0012).
- Requirements and context meter are Case File state, folded from events (0013).
- Conditional requirements are waived by tool; insurer queries are answered by tool (0014).
- Doc verdicts are set by code; validation is deterministic until step 4; approval needs a current passing verdict (0015).

## What the owner said that isn't obvious from the design

- Keep the SOP and skills **very terse**; they will be iterated soon.
- Use **tweaked production documents**, not hand-made mock documents, for end-to-end tests ("fake docs look stupid"). The owner supplies them.
- Context compression's purpose is to be a proof of concept of how it should work, not to save tokens.
- Show the Context tab: green for what is still in the prompt, red for what has left it. Low priority; a static page is acceptable.
- Reduce latency as much as possible (parallel tool calls, streaming activity).
- One endorsement per case now; multi-change support later (the schema is list-ready).
- Multi-change later: a document required by more than one endorsement in a case is requested once, and conflicting rules between loaded skills must be reconciled.

## Real-world failure modes worth reproducing as eval scenarios

Generic descriptions only; the production specifics stay out of this repo.

- The agent re-asks for something the user already provided (after a resumed or deduplicated turn).
- The model returns a short or reworded key that does not match the canonical type, and the merge silently drops it.
- A document is extracted but never read by the model, or extraction fails and the identifiers vanish.
- The validation verdict flips between turns because it is re-derived without the previous verdict.
- A free-text rule condition forces a pointless ask.
- A stale reply is re-posted after a crash.
- Ask budget gets consumed by asks that were never delivered.
- A document of the wrong type is mislabelled and fills the wrong slot.

## Known risks the owner accepted

- The demo may use an existing Azure OpenAI resource for now, behind strict caps (0011). Moving to personal keys must stay an env-var change.
- Tweaked production documents carry residual re-identification risk (QR codes, photos, metadata). The tweak guidelines in `fixtures/documents/README.md` are mandatory, and the owner is responsible for the final check before any file is committed.

## Out of scope for v1

Multi-change cases, durable shareable replay links, judge calibration, prompt-injection and fault-injection suites, `seating-capacity-change` and `ncb-recovery` skills, RAG.
