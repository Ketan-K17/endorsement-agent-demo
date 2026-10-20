# ADR-0006: Interactive approval; real documents stay out of the repo

Status: accepted (user decisions)

**Approval.** The demo user is both customer and approver. `request_approval` raises a LangGraph `interrupt()`; the UI's Approval panel resumes it. Evals plug in a scripted/LLM reviewer behind the same interface, covering rejections too.

**Test documents.** Real production documents are used only for private end-to-end testing, from a local `private_docs/` stash that is `.gitignore`d. A curated redacted/synthetic suite will be added later for end users to try. Originals never enter git history.
