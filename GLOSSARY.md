# Glossary

**Endorsement** — a change to an existing insurance policy (owner, nominee, address, seating capacity, …). Not a new policy.

**Case** — one conversation handling exactly one endorsement request (v1).

**Case File** — typed, event-sourced state of a case. The single source of truth; tools mutate it, the model reads a rendering of it.

**Slot** — a named piece of information the case needs (e.g. `new_owner_name`), with value, source and confidence.

**Source** — where a slot value came from: `user_msg` or `doc:<id>`.

**Document (Doc)** — a user-uploaded file with a classified type, quality verdict and extracted fields.

**Required docs** — the documents an endorsement type needs for a given insurer, from the rules master.

**Part** — one side or page of a document type that comes in several (`doc_parts` in the rules master: Aadhaar front/back, policy copy page_1/page_2). A required doc is `partial` until every part is accepted.

**SOP** — the standard operating procedure for handling endorsements. Invented for this demo. Lives wholly in the system prompt.

**System prompt** — role + basic guidelines + full SOP.

**Static prefix** — system prompt + tool definitions. Identical on every call; cacheable.

**Trajectory** — static prefix + chat history (user/assistant/tool messages; tool calls are part of assistant messages) + status bar.

**Skill** — a folder (`SKILL.md` + optional `references/`) bundling the workflow knowledge for one endorsement type or cross-cutting behaviour; loaded on demand.

**Skill catalog** — name + one-line "use when…" per skill, embedded in the `load_skill` tool definition.

**Reference file** — specialised document inside a skill's `references/`, fetched with `read_skill_file`.

**Status bar** — ephemeral rendering of the Case File appended as the final `user` message of each model call (for now) and streamed to the UI; never stored in history.

**Stage** — Intake → Docs → Validate → Approval → Insurer → Done (or Handover); computed from state, never stored.

**Ask** — a batched question set sent to the customer via `ask_user`. **Ask budget** — max asks per case, enforced in code.

**Verdict** — the result of `validate_case`. **Carry-forward** — each validation receives the previous verdict and returns a diff, preventing flip-flops.

**Approval** — human decision before insurer submission. In the demo the user plays customer *and* approver.

**Insurer** — the mock external party that receives the submission and may raise queries.

**Handover** — structured escalation to a human team, ending autonomous handling.

**Tool-result compression** — replacing older tool results in history with short stubs once enough accumulate; near-lossless, originals kept only in the event log.

**Image stubbing** — replacing an uploaded image in history with a text stub once its extraction is done.

**Event log** — append-only record of all case events, including originals of compressed/stubbed content.

**Scenario** — an eval case: persona script + doc fixtures + mock-world config + assertions. **Invariant** — an assertion that must hold in every run.

**pass@1 / pass^k** — probability a single run passes / probability all k runs pass.

**Case folder** — a directory under `fixtures/documents/` holding one customer story's tweaked documents. **Persona** — the invented values in `personas.yaml` that every document in a case must match. **expected.json** — agreed ground-truth values for a case.

**Context tab** — UI view of the full message log: green = still in the current prompt, red = removed from it (kept visible).

**Demo policies picker** — UI list of seeded policies that starts a flow with a pre-filled message.
