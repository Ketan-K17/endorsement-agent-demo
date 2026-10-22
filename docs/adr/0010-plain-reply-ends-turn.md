# ADR-0010: A plain assistant message ends the turn; no `send_reply`

Status: accepted

**Decision.** The model's final plain-text message is the reply. `ask_user` remains only as a logging and ask-budget gate (budget 3 per case); the question text lives in the reply. Its trivial ack result is excluded from the compression count.

**Why.** Two ways to reply invite double replies and extra tool results to compress.
