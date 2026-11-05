# ADR-0016: Fixture documents from templates

Status: accepted (templates instead of tweaked production documents, and the one wiped policy, by the user, 2026-11-05; the rest proposed by the assistant)

**Context.** The design had the owner tweak real production documents by hand. That is slow and carries re-identification risk. Public templates give realistic layouts without it.

**Decision.**
- **Fixtures are built from templates** the owner found online, filled with persona values by a script. The inputs and script live in untracked `private_docs/`; only the output PNGs are committed.
- **One production document is the exception:** the policy copy. Its layout is used for the schedule pages only (2 of 9). All text and images are removed, including the diagonal watermark and hidden white text. Only allowlisted labels and persona values are drawn back, so nothing else can survive.
- **A policy copy is two files**, `policy_copy.png` and `policy_copy_p2.png`, so small print stays legible; the nominee is on page 2. An RC is one image, front above back.
- **Government-format fixtures (RC, Aadhaar, PAN) carry a visible SPECIMEN mark and a dummy QR.** The repo is public, and these should not pass as genuine. Policy copies carry a footer naming the insurer as fictional instead. The Form 30 is a blank public form and is not marked.

**Consequences.** Fixtures are reproducible while `private_docs/` exists. Vision models will see the SPECIMEN mark, so extraction and fraud-looking scenarios must not treat it as a signal. Values with no persona field (dates, colour, VID, premiums) are invented in the script and settled in `expected.json`.
