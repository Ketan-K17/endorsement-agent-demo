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
│ user / assistant / tool-call / tool-result messages, entire    │
├ STATUS BAR (ephemeral, regenerated every model call) ──────────┤
│ rendered from the Case File, always the final block            │
└─────────────────────────────────────────────────────────────────┘
```

- The status bar is built per call and **never persisted** to history or the checkpointer, so stale copies cannot exist.
- Because everything above the bar only grows (or changes at compression events), the provider-side prefix cache stays warm.
- **Skill catalog placement:** inside the `load_skill` tool definition (an enum of skill names plus a one-line "use when…" per skill, generated from `SKILL.md` frontmatter at startup). It is part of the static prefix, sits next to the tool that uses it, and keeps the system prompt to SOP and guidelines. See ADR-0002.

## 3. Case File (typed state)

Event-sourced: an append-only event list; state is a fold over it. Enables replay for evals and a UI timeline.

```
CaseFile
  case_id, created_at
  policy: PolicySnapshot | None
  change_request: {type, details} | None          # one per case in v1; schema is list-ready
  slots: {name -> Slot{value, source, confidence, superseded_by?}}
  documents: [Doc{id, filename, type, quality, extraction, verdict}]
  validation: [Verdict{ts, outcome, issues[], diff_vs_prev}]
  asks: [Ask{ts, questions[], reason}]            # ask log
  approval: {status: none|pending|approved|rejected, reason?}
  insurer: {ref?, stage, last_message?}
  loaded_skills: [name]
  handover: {team, reason, severity} | None
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
| Documents | `list_documents()` | Uploaded files + processing status |
| | `classify_document(doc_id)` | Vision. Doc type + quality verdict |
| | `extract_fields(doc_id, schema)` | Vision. Values + per-field confidence |
| | `cross_check(slot_a, slot_b)` | Name / reg-no / chassis consistency |
| Skills | `load_skill(name)` | Returns `SKILL.md`; catalog lives in this tool's definition |
| | `read_skill_file(skill, path)` | Reads a file under that skill's `references/`; sandboxed to the skill directory |
| Conversation | `ask_user(questions[], reason)` | Batched; passes the ask-budget guardrail; logged |
| | `send_reply(text, kind)` | User-facing message |
| Validation | `validate_case()` | Deterministic checks + LLM pass; receives prior verdict and returns a diff (carry-forward) |
| Submission | `request_approval(summary)` | Pauses the graph (`interrupt()`); the user approves in the UI |
| | `submit_to_insurer(case_id)` | Code-enforced: only if `approval.status == approved`; idempotent |
| | `check_insurer_status(ref)` | Polls the mock insurer state machine (see below) |
| Escalation | `handover(team, reason, severity)` | Ends autonomous handling with a structured note |

`check_insurer_status`: after submission the insurer responds asynchronously. The mock is a scripted state machine per scenario, e.g. `received → query_raised("seller NOC unclear") → approved → issued`. An insurer query must be turned into a user ask. Drives the last stages of the status bar.

## 5. Skills

```
skills/<name>/
  SKILL.md        frontmatter: name, description ("use when…"), tools_hint
                  body: workflow, required docs, pitfalls, list of references with "read when…"
  references/*.md specialised material, fetched via read_skill_file
```

Three disclosure levels: catalog line (static prefix) → `SKILL.md` (`load_skill`) → reference file (`read_skill_file`).

Endorsement-type skills: `change-of-owner`, `nominee-update`, `address-change`, `seating-capacity-change`, `ncb-recovery`, `vehicle-detail-correction`, `hypothecation-change`.
Cross-cutting skills: `document-triage`, `slot-filling-etiquette`, `insurer-queries`, `escalation-policy`.

v1 = one change per case. Multi-change (two type skills in one case, shared docs asked once, conflicting rules reconciled) is a roadmap item; the Case File is shaped for it.

## 6. History transforms

Both transforms are applied to stored history, deterministically, and the originals are kept in the event log.

### 6.1 Image stubbing
Uploaded images stay in context only until `classify_document` and `extract_fields` have run for that doc; then the image part is replaced in place with `[image doc_3 — see extraction above]`.

### 6.2 Tool-result compression (proof of concept)
Purpose: demonstrate how context compression should work, not primarily to save tokens.

- **Targets only tool results.** User/assistant messages and tool calls are never touched.
- **Trigger:** when the number of *uncompressed* tool results in the trajectory reaches `COMPRESS_THRESHOLD` (default **5**, configurable). A result that has been compressed is never counted again and never recompressed.
- **Action:** compress all uncompressed tool results **except the most recent one** (the latest tool call stays raw). Batch, not per-turn, so the cached prefix changes only at compression events.
- **Near-lossless:** the compressor (a small model, per-tool prompt) removes wording, boilerplate and repeated structure only. It keeps every identifier, value, confidence, decision and error state. Example stub: `[compressed #r12 extract_fields(doc_3): doc_type=RC; reg_no=KA01AB1234; owner="A. Rao"; chassis=…(conf 0.62); engine=…(conf 0.91); issues=none]`.
- **No restore tool.** Originals are kept in the event log for audit/replay and evals, not exposed to the model. The Case File remains the source of truth for slot values.
- **Visible:** each compression emits a `context.compressed` event → trace span, UI timeline chip (`compressed 4 results, 4.1k → 1.2k tokens`), and a status-bar context meter.

## 7. Guardrails (code, not prompts)

Ask budget (max asks/case; excess forces summarise-or-handover), tool-call cap per turn, wall-clock timeout, idempotency keys on approval/submit, arg schema validation, PII redaction in logs/traces, untrusted-content delimiting for document text. Submission requires approval, enforced in `submit_to_insurer`, not in the prompt.

## 8. Status bar

Pure function `render_status(case) -> StatusBar`, serialised two ways: compact text appended to the model call (§2) and JSON streamed to the UI over SSE.

Fields: `stage` (computed from state predicates, never stored), `active_skills`, `docs_checklist[{name,state,reason}]`, `slots{filled,total,low_conf[]}`, `ask_budget{used,max}`, `validation{verdict,changed_since_last}`, `approval{status}`, `insurer{stage,ref}`, `context{uncompressed_tool_results,threshold,last_compressed_at}`, `current_activity` (UI only), `trace_url` (UI only).

Stages: Intake → Docs → Validate → Approval → Insurer → Done (or Handover).

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

CI: fast suite on PR (A + ~10 scenarios at k=1); full suite nightly; results table committed as `EVALS.md`; gate on zero invariant violations and per-category thresholds.

## 11. Stack

- Orchestration: **LangGraph** (agent node + tool node, checkpointer, `interrupt()` for approval, streaming).
- LLMs: **Azure OpenAI**, behind a role-based interface (agent / extractor / compressor / judge), deployment per role from config. Probed 2026-10-20 (all passed chat, tool calling, vision, strict JSON schema): US resource `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5.4-mini`, `gpt-5.4-nano`, `o4-mini`; India resource `gpt-5.6-sol`, `gpt-5`, `gpt-5-mini`, `gpt-5-nano`. No 5.5-family deployment exists on either. Confirmed roles: agent `gpt-5.6-sol` (India), extractor `gpt-5.4-mini`, compressor `gpt-5.4-nano`, judge `gpt-5` (a different model from the agent). Confirmed by the user 2026-10-20; may be revisited from eval numbers. The agent runs on the India resource and the other roles on the US resource, so config holds two endpoints.
- Tracing: **Langfuse cloud**.
- Backend: FastAPI + SSE. Frontend: small static app (chat, status bar, approval panel, event timeline).
- Hosting: Hugging Face Spaces (Docker) preferred; Render free as fallback. Public endpoint ⇒ per-session turn cap, upload size cap, rate limit, optional access gate.

## 12. Test documents

Real production documents are used only for private end-to-end testing from a local stash that is never committed (`.gitignore`d `private_docs/`). The repo ships a curated suite of redacted/synthetic docs chosen later for end users to try.

## 13. Open items

- Revisit model-per-role after the first eval runs.
- Doc suite selection (user, later).
