# ADR-0015: Tool gates and loop mechanics

Status: accepted (doc verdicts, validation scope, skill messages, short results and the date by the user, 2026-10-24; the rest proposed by the assistant)

**Context.** Building the tools and loop (step 3) hit points DESIGN §4–§7 does not settle: nothing set a document's verdict, `validate_case`'s LLM pass had no test data, and the interrupt, cap and compression mechanics needed concrete rules.

**Decision.**
- **Document verdicts are set by code.** `classify_document` rejects a `poor` or `unreadable` doc with the reason. `extract_fields` accepts a clear doc whose type is a required doc. Other types get no verdict. No `review_document` tool.
- **`validate_case` is deterministic for now:** policy selected and active, change request and rules present, docs accepted or waived, required slots filled, no slot below 0.7, document `policy_no`/`reg_no` equal to the policy's. Issues come out in a fixed order; `diff_vs_prev` lists `+`/`-` lines. The LLM pass is added in step 4, once real extractions exist.
- **`request_approval` needs a current verdict:** the latest validation passed and is newer than every event that changes what it checked.
- **`lookup_policy` selects the policy only on a single match.** Several matches are listed for the user to choose from; no `select_policy` tool.
- **Refusals are tool results** (`refused: …`, `error: …`), never exceptions, so the model can recover.
- **Approval interrupt and re-run.** LangGraph re-runs the tool node on resume. Calls already recorded as `tool.result` reuse their stored result; a pending approval is not requested twice. Parallel calls run first, then the approval.
- **Tool-call cap.** Calls beyond `MAX_TOOL_CALLS_PER_TURN` are refused; the next model call keeps the tool definitions (cache) but sets `tool_choice="none"`.
- **Originals in the event log.** `tool.result` carries the raw result; `context.compressed` carries each stub; `history.image_stubbed` records each stubbed upload; `insurer.responded` records query answers.
- **Uploads** are one user message each, id `upload-<doc_id>`, which is how stubbing finds them.
- **Token counts** for the compression chip are a 4-chars-per-token estimate.
- **Skill text is a user message, not a tool result** (user, after the first live run). `load_skill` and `read_skill_file` return `loading skill <name>` / `loading skill file <path>`; the text follows the batch's tool results as a user message (id `skill-<call_id>`), so compression never touches it. It does not reset the per-turn tool-call count, and `tool.result` keeps it as `attachment` for replay.
- **Short results are already compressed** (user). A result under 400 characters (`COMPRESS_MIN_CHARS`) is never counted toward the trigger or compressed: a stub carries about 80 characters of overhead, so anything shorter would not shrink. The first live run compressed acks like `recorded new_owner_phone=…` into longer stubs.
- **Today's date is in the status bar** (user). `render_status(case, today)` stays pure; the loop passes the date in Asia/Kolkata. Conditions like "transfer more than 14 days ago" need it, and the static prefix stays cacheable.

**Consequences.** The Docs stage moves without model judgement, which evals can assert exactly. A wrong classification can still accept the wrong doc type; the `cross_check` and validation identifiers are the backstop, and a classification eval covers it.
