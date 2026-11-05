# Endorsement Agent — Design

Status: draft v0.1. Terms are defined in [GLOSSARY.md](GLOSSARY.md); decisions in [docs/adr](docs/adr).

A portfolio demo of an agentic (non-deterministic) insurance-endorsement assistant. All data is mocked/synthetic. The user plays **customer and approver**.

## 1. Principles

1. **One model loop, no fixed graph.** The model picks tools and order. Code owns the rails (budgets, gates, validation).
2. **State lives in the Case File, not in prose.** Tools mutate it; the model reads it.
3. **Full history, never truncated.** Only two sanctioned transforms touch history: image stubbing and tool-result compression (§6).
4. **No RAG.** Knowledge is static context (SOP) or skills.
5. **The status bar is derived, ephemeral, and last.**

## 2. Prompt anatomy (what the model sees, in order)

```
┌ STATIC PREFIX (cacheable, identical every call) ───────────────┐
│ system prompt   = role + basic guidelines + full SOP           │
│ tool definitions (incl. load_skill with the skill catalog)     │
├ TRAJECTORY (append-only except §6 transforms) ─────────────────┤
│ user / assistant / tool messages, entire                        │
├ STATUS BAR (ephemeral, regenerated every model call) ──────────┤
│ rendered from the Case File, sent as the final user message    │
└─────────────────────────────────────────────────────────────────┘
```

- Four roles only: `system`, `user`, `assistant`, `tool`. History is stored in LangChain's message format, so it is forced into a compatible shape. A tool call is not a separate message: an `assistant` message has two fields, `content` and `tool_calls`. When the agent calls tools, `content` is empty and `tool_calls` is non-empty; when it replies in text, `content` is filled and `tool_calls` is empty. Each call's output comes back as a `tool` message (LangChain `ToolMessage`).
- The status bar is appended as a final `user` message (for now) so it fits the four-role format. It is built per call and **never persisted** to history or the checkpointer, so stale copies cannot exist.
- Because everything above the bar only grows (or changes at compression events), the provider-side prefix cache stays warm.
- **Skill catalog placement:** inside the `load_skill` tool definition (an enum of skill names plus a one-line "use when…" per skill, generated from `SKILL.md` frontmatter at startup). It is part of the static prefix, sits next to the tool that uses it, and keeps the system prompt to SOP and guidelines. See ADR-0002.

## 3. Case File (typed state)

Event-sourced: an append-only event list; state is a fold over it. Enables replay for evals and a UI timeline.

```
CaseFile
  case_id, created_at, ask_budget
  policy: PolicySnapshot | None
  change_request: {type, details} | None          # one per case in v1; schema is list-ready
  requirements: {docs[{name, condition?}], slots[{name, condition?}]} | None   # from rules.loaded (ADR-0013)
  waivers: {requirement name -> reason}                                       # from requirement.waived (ADR-0014)
  slots: {name -> Slot{value, source, confidence, supersede_reason?}}          # current value; history in event log
  documents: [Doc{id, filename, type, quality, extraction, verdict}]
  validation: [Verdict{ts, outcome, issues[], diff_vs_prev}]
  asks: [Ask{ts, questions[], reason}]            # ask log
  approval: {status: none|pending|approved|rejected, reason?}
  insurer: {ref?, stage, last_message?}
  loaded_skills: [name]
  handover: {team, reason, severity} | None
  context: {uncompressed_tool_results, threshold, last_compressed_at}   # from tool.result / context.compressed
```

## 4. Tools

Small and coarse-grained. Every write goes through a validated tool.

| Group | Tool | Notes |
|---|---|---|
| Case | `get_case()` | Compact render of the Case File |
| | `record_slot(name, value, source, confidence)` | Only way to write a slot. Refuses to overwrite higher-confidence values unless `supersede=True` + reason |
| | `record_change_request(type, details)` | Sets the case's endorsement type |
| Policy | `lookup_policy(policy_no \| reg_no \| phone)` | Mock policy store; may return several matches |
| | `get_endorsement_rules(type, insurer)` | Required docs / fees / TAT from the mock rules master |
| | `waive_requirement(name, reason)` | Marks a conditional requirement as not applying; refuses unconditional ones (ADR-0014) |
| Documents | `list_documents()` | Uploaded files + processing status |
| | `classify_document(doc_id)` | Vision. Doc type + quality; poor/unreadable docs are rejected (ADR-0015) |
| | `extract_fields(doc_id, schema)` | Vision. Values + per-field confidence; a clear doc of a required type is accepted |
| | `cross_check(slot_a, slot_b)` | Name / reg-no / chassis consistency |
| Skills | `load_skill(name)` | Result is `loading skill <name>`; `SKILL.md` follows as a user message (ADR-0015); catalog lives in this tool's definition |
| | `read_skill_file(skill, path)` | Reads a file under that skill's `references/`, sent like `load_skill`; sandboxed to the skill directory |
| Conversation | `ask_user(questions[], reason)` | Budget gate + log only (ask budget 3). The question text itself is carried by the model's plain reply. The ack result is trivial and excluded from the compression count |
| Validation | `validate_case()` | Deterministic checks, then an LLM consistency pass on the judge role (ADR-0017); receives prior verdict and returns a diff (carry-forward) |
| Submission | `request_approval(summary)` | Pauses the graph (`interrupt()`); the user approves in the UI |
| | `submit_to_insurer(case_id)` | Code-enforced: only if `approval.status == approved`; idempotent |
| | `check_insurer_status(ref)` | Polls the mock insurer state machine (see below) |
| | `respond_to_insurer(ref, message, doc_ids?)` | Answers an open insurer query; the state machine holds until then (ADR-0014) |
| Escalation | `handover(team, reason, severity)` | Ends autonomous handling with a structured note |

A turn ends when the model emits a plain assistant message with no tool call; that message is the reply (there is no `send_reply` tool, ADR-0010). Parallel tool calls are allowed (§15).

`check_insurer_status`: after submission the insurer responds asynchronously. The mock is a scripted state machine per scenario, e.g. `received → query_raised("seller NOC unclear") → approved → issued`. An insurer query must be turned into a user ask, and the answer sent back with `respond_to_insurer`; the machine waits at the query until then. Drives the last stages of the status bar.

## 5. Skills

```
skills/<name>/
  SKILL.md        frontmatter: name, description ("use when…"), tools_hint
                  body: workflow, required docs, pitfalls, list of references with "read when…"
  references/*.md specialised material, fetched via read_skill_file
```

Three disclosure levels: catalog line (static prefix) → `SKILL.md` (`load_skill`) → reference file (`read_skill_file`).

v1 type skills (terse; to be iterated): `change-of-owner`, `nominee-update`, `name-correction`.
Cross-cutting skills (terse): `document-triage`, `slot-filling-etiquette`, `insurer-queries`, `escalation-policy`.
Roadmap type skills: `seating-capacity-change`, `ncb-recovery` (added later to show a new skill is cheap).

v1 = one change per case. Multi-change (two type skills in one case, shared docs asked once, conflicting rules reconciled) is a roadmap item; the Case File is shaped for it.

## 6. History transforms

Both transforms are applied to stored history, deterministically, and the originals are kept in the event log.

### 6.1 Image stubbing
Uploaded images stay in context only until `classify_document` and `extract_fields` have run for that doc; then the image part is replaced in place with `[image doc_3 — see extraction above]`.

### 6.2 Tool-result compression (proof of concept)
Purpose: demonstrate how context compression should work, not primarily to save tokens.

- **Targets only tool results.** User and assistant messages (including the tool calls inside them) are never touched.
- **Trigger:** when the number of *uncompressed* tool results in the trajectory reaches `COMPRESS_THRESHOLD` (default **5**, configurable). A result that has been compressed is never counted again and never recompressed. Parallel results count individually; `ask_user` acks and results under 400 characters (already compact) are excluded. Skill text never enters a tool result (§4).
- **Action:** compress all uncompressed tool results **except the most recent one** (the latest tool result stays raw). Batch, not per-turn, so the cached prefix changes only at compression events.
- **Near-lossless:** the compressor (a small model, per-tool prompt) removes wording, boilerplate and repeated structure only. It keeps every identifier, value, confidence, decision and error state. Example stub: `[compressed #r12 extract_fields(doc_3): doc_type=RC; reg_no=KA01AB1234; owner="A. Rao"; chassis=…(conf 0.62); engine=…(conf 0.91); issues=none]`.
- **No restore tool.** Originals are kept in the event log for audit/replay and evals, not exposed to the model. The Case File remains the source of truth for slot values.
- **Visible:** each compression emits a `context.compressed` event → trace span, UI timeline chip (`compressed 4 results, 4.1k → 1.2k tokens`), and a status-bar context meter.

## 7. Guardrails (code, not prompts)

Ask budget (max asks/case; excess forces summarise-or-handover), tool-call cap per turn, wall-clock timeout, idempotency keys on approval/submit, arg schema validation, PII redaction in logs/traces, untrusted-content delimiting for document text. Submission requires approval, enforced in `submit_to_insurer`, not in the prompt.

## 8. Status bar

Pure function `render_status(case, today) -> StatusBar`, serialised two ways: compact text appended to the model call (§2) and JSON streamed to the UI over SSE.

Fields: `today` (passed in; dynamic facts belong here, not in the static prefix), `stage` (computed from state predicates, never stored), `active_skills`, `docs_checklist[{name,state,reason}]`, `slots{filled,total,low_conf[]}`, `ask_budget{used,max}`, `validation{verdict,changed_since_last}`, `approval{status}`, `insurer{stage,ref}`, `context{uncompressed_tool_results,threshold,last_compressed_at}`, `current_activity` (UI only), `trace_view` (UI only; in-app, not a Langfuse link, ADR-0009). The two UI-only fields are added by the API layer, not by `render_status` (ADR-0013).

Stages, computed from state in order (never stored):
Intake (no change request yet) → Docs (required docs not all `accepted`) → Validate (all docs in, no passing verdict) → Approval (verdict passes, no decision) → Insurer (approved, not issued) → Done. Handover applies at any point.

Guardrail defaults (config): ask budget 3 per case; 12 tool calls per turn; `validate_case` is forced before `request_approval`.

## 9. Approval (interactive)

The user is both customer and approver. `request_approval` raises a LangGraph `interrupt()`; the UI shows an Approval panel (case summary, diff vs policy, Approve / Reject / Request changes). The decision resumes the graph; rejection reasons return to the agent as tool results. The same interface is implemented by a scripted/LLM reviewer for evals (approving *and* rejecting).

## 10. Evals

Judge-vs-agent: use different models where possible.

**A. Component** (every PR): doc-classification accuracy/confusion; extraction field-F1 + calibration; skill-selection accuracy incl. ambiguous messages; status-bar render snapshot tests.
**B. Scenario** (core): `{persona script, doc fixtures, mock-world config, assertions}`; a simulated user with hidden ground truth plays the customer, a scripted reviewer plays the approver. Assertions on the final Case File + event log:
- outcome: correct type, slots match ground truth, docs collected/flagged correctly
- hard invariants: never submitted without approval; never re-asked a provided value; asks ≤ budget; no PII in logs; no invented policy facts
- handover correctness: escalates when it should, not when it shouldn't
- efficiency (trend only): turns, tool calls, tokens
Run each scenario k=5; report pass@1 and pass^k.
**C. LLM judge**: tone/clarity of asks; reply faithful to SOP. Pinned judge model, rubric calibrated against ~30 hand-labelled transcripts; agreement published.
**D. Compression**: (i) *needle-after-compression* — a fact only present in a since-compressed result must still be used correctly (via the stub or the Case File); (ii) no re-ask after compression; (iii) compression off vs on → outcome parity; (iv) compressor fidelity on a labelled set (required identifiers survive).
**E. Regression / adversarial / fault**: failure-mode library (re-ask after dedup, short key not mapping to a canonical type, stale reply replay, doc extracted but never read, verdict flip-flop across turns); prompt injection inside a document; user trying to skip approval; insurer timeout; extraction failure; malformed tool output.

CI: fast suite on PR (A + ~10 scenarios at k=1); full suite nightly; results table committed as `EVALS.md`; gate on zero invariant violations and per-category thresholds. CI needs a model key.

**v1 scope** (ADR-0012): component evals for classification and extraction on the fixture documents; ~12 scenarios (4 per skill, including one approver rejection, one fraud-looking mismatch, one self-contradicting user, one compression needle); the compression evals; invariants on every run; k=3 nightly, k=1 on PR. Deferred to v1.1: judge calibration, prompt-injection and fault-injection suites.

## 11. Stack

- Orchestration: **LangGraph** (agent node + tool node, checkpointer, `interrupt()` for approval, streaming).
- LLMs: **Azure OpenAI**, behind a role-based interface (agent / extractor / compressor / judge), deployment per role from config. Probed 2026-10-20 (all passed chat, tool calling, vision, strict JSON schema): US resource `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5.4-mini`, `gpt-5.4-nano`, `o4-mini`; India resource `gpt-5.6-sol`, `gpt-5`, `gpt-5-mini`, `gpt-5-nano`. No 5.5-family deployment exists on either. Confirmed roles: agent `gpt-5.6-sol` (India), extractor `gpt-5.4-mini`, compressor `gpt-5.4-nano`, judge `gpt-5` (a different model from the agent). Confirmed by the user 2026-10-20; may be revisited from eval numbers. The agent runs on the India resource and the other roles on the US resource, so config holds two endpoints.
- Tracing: **Langfuse cloud**, a personal project (not a self-hosted instance). Visitors never see Langfuse links (ADR-0009).
- Backend: FastAPI + SSE. Frontend: one static page (plain HTML/CSS/JS, `EventSource`, no build step).
- Hosting: Hugging Face Spaces (Docker, `app_port: 7860`, SSE buffering disabled); Render free as fallback. Free tier: ephemeral disk, sleeps after ~48h idle, ~1 min cold start. To re-verify at deploy time.
- Credentials: an existing Azure OpenAI resource is used for now and may change to personal keys; the role-based config makes that an env-var change (ADR-0011).

## 12. Test documents

Templates and any production source stay in a local stash that is never committed (`.gitignore`d `private_docs/`). The repo ships a curated suite of docs filled from `personas.yaml` for end users to try, under `fixtures/documents/` (one folder per case, guidelines in its README; ADR-0016). Ground truth per case is `expected.json`, agreed after running the extractor.

## 13. Mock world

- Three fictional insurers: Northwind General, Cedar Mutual, Halcyon Assurance.
- Policy master derived from the tweaked fixture documents (docs first, policies second), about 15 policies, shown in a "Demo policies" picker that drops a starter message into the chat. Unknown numbers return not-found.
- Rules master mirrors the shape of the production rulebook (classification, insurer, item, upload-or-text, free-text conditions, handover datapoints), invented content: 3 insurers × 3 types, about 40 rows, plus 2–3 invented conditional twists per insurer. The free-text conditions are what the model must interpret.
- SOP, skills and references are written fresh, terse, from public knowledge; no proprietary text is copied.

## 14. UI

Single static page: chat pane, status bar, approval card, live activity feed (tool events with timings), in-app trace/replay view, and a **Context tab**: the full message log with items still in the current prompt in green and items that have left it (old status bars, compressed originals, stubbed images) kept visible in red. Tokens stream over SSE; the status bar updates after each tool result and at the end of each turn, never mid-token. A static Context page is acceptable if the animated version proves costly.

## 15. Latency, limits and abuse controls

- Target under 90 seconds per user turn. Parallel tool calls enabled (documents classified and extracted concurrently); every tool event is streamed with timing.
- Per session: 60 model calls and 150k tokens. Per IP: 3 sessions per day. A global daily budget switch. When a cap trips, the UI says so and offers a pre-recorded run.
- An optional invite code (env var) opens or closes access without a redeploy.

## 16. Events and replay

One event schema feeds the UI feed, the status bar, the Context tab, the replay, the Langfuse trace and the eval assertions (ADR-0008). The user's own session replay works while the session lives. Curated example runs are committed as static event logs. Shareable user-session links are dropped (ephemeral disk).

## 17. Build order

1. Case File, event store, `render_status` with snapshot tests.
2. Mock world: policies, rules master, insurer state machine.
3. Tools, then the LangGraph loop with status bar, image stubbing, compression.
4. Extraction against the fixture documents.
5. API + SSE, then the UI.
6. Evals and nightly runs.
7. Deploy to Spaces with the limits.

## 18. Repo

Public GitHub repo `endorsement-agent`, MIT license, README states all data is synthetic and derived from tweaked documents, and shows the nightly eval table.

## 19. Open items

- Revisit model-per-role after the first eval runs.
- Final doc set (cases 02, 04, 06 still need building per `fixtures/documents/README.md`).
