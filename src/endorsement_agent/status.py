"""Status bar: a pure function of the Case File and today's date (DESIGN §8, ADR-0003).

Serialised as JSON for the UI and as compact text for the model. Never persisted.
`current_activity` and `trace_view` are UI-only and added by the API layer.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel

from endorsement_agent.case_file import CaseFile, Doc
from endorsement_agent.events import DocRequirement

LOW_CONFIDENCE = 0.7

Stage = Literal["Intake", "Docs", "Validate", "Approval", "Insurer", "Done", "Handover"]
DocState = Literal["missing", "received", "partial", "accepted", "rejected", "waived"]


class DocCheck(BaseModel):
    name: str
    state: DocState
    reason: str | None = None


class SlotsSummary(BaseModel):
    filled: int
    total: int
    low_conf: list[str]


class AskBudget(BaseModel):
    used: int
    max: int


class ValidationSummary(BaseModel):
    verdict: Literal["none", "pass", "fail"]
    changed_since_last: bool


class InsurerSummary(BaseModel):
    stage: str
    ref: str | None


class ContextMeter(BaseModel):
    uncompressed_tool_results: int
    threshold: int
    last_compressed_at: AwareDatetime | None


class StatusBar(BaseModel):
    today: date
    stage: Stage
    active_skills: list[str]
    docs_checklist: list[DocCheck]
    slots: SlotsSummary
    ask_budget: AskBudget
    validation: ValidationSummary
    approval: str
    insurer: InsurerSummary
    context: ContextMeter


def _check(req: DocRequirement, docs: list[Doc], waivers: dict[str, str]) -> DocCheck:
    name = req.name
    if name in waivers:
        return DocCheck(name=name, state="waived", reason=waivers[name])
    matching = [d for d in docs if d.type == name]
    accepted = [d for d in matching if d.verdict == "accepted"]
    if accepted:
        # Accepted only once the accepted uploads cover every part (ADR-0023).
        covered = {p for d in accepted for p in d.parts}
        if needed := [p for p in req.parts if p not in covered]:
            return DocCheck(name=name, state="partial", reason=f"needs {', '.join(needed)}")
        return DocCheck(name=name, state="accepted")
    if not matching:
        return DocCheck(name=name, state="missing", reason=req.condition)
    latest = matching[-1]
    if latest.verdict == "rejected":
        return DocCheck(name=name, state="rejected", reason=latest.verdict_reason)
    return DocCheck(name=name, state="received")


def docs_checklist(case: CaseFile) -> list[DocCheck]:
    if case.requirements is None:
        return []
    return [_check(r, case.documents, case.waivers) for r in case.requirements.docs]


def stage(case: CaseFile) -> Stage:
    """Computed from state predicates, in order. Never stored."""
    if case.handover is not None:
        return "Handover"
    if case.change_request is None:
        return "Intake"
    if case.requirements is None or any(
        c.state not in ("accepted", "waived") for c in docs_checklist(case)
    ):
        return "Docs"
    if not case.validation or case.validation[-1].outcome != "pass":
        return "Validate"
    if case.approval.status != "approved":
        return "Approval"
    if case.insurer.stage != "issued":
        return "Insurer"
    return "Done"


def render_status(case: CaseFile, today: date) -> StatusBar:
    slot_reqs = case.requirements.slots if case.requirements else []
    required = [r.name for r in slot_reqs if r.name not in case.waivers]
    last = case.validation[-1] if case.validation else None
    return StatusBar(
        today=today,
        stage=stage(case),
        active_skills=list(case.loaded_skills),
        docs_checklist=docs_checklist(case),
        slots=SlotsSummary(
            filled=sum(name in case.slots for name in required),
            total=len(required),
            low_conf=sorted(n for n, s in case.slots.items() if s.confidence < LOW_CONFIDENCE),
        ),
        ask_budget=AskBudget(used=len(case.asks), max=case.ask_budget),
        validation=ValidationSummary(
            verdict=last.outcome if last else "none",
            changed_since_last=bool(last and last.diff_vs_prev),
        ),
        approval=case.approval.status,
        insurer=InsurerSummary(stage=case.insurer.stage, ref=case.insurer.ref),
        context=ContextMeter(
            uncompressed_tool_results=case.context.uncompressed_tool_results,
            threshold=case.context.threshold,
            last_compressed_at=case.context.last_compressed_at,
        ),
    )


def to_text(bar: StatusBar) -> str:
    """Compact form appended as the final user message of each model call."""
    docs = "; ".join(
        f"{c.name}={c.state}" + (f" ({c.reason})" if c.reason else "") for c in bar.docs_checklist
    )
    low = f" low_conf={','.join(bar.slots.low_conf)}" if bar.slots.low_conf else ""
    changed = " (changed)" if bar.validation.changed_since_last else ""
    ref = f" ref={bar.insurer.ref}" if bar.insurer.ref else ""
    lines = [
        f"[STATUS] today={bar.today.isoformat()} stage={bar.stage}"
        f" skills={','.join(bar.active_skills) or '-'}",
        f"docs: {docs or '-'}",
        f"slots: {bar.slots.filled}/{bar.slots.total}{low}",
        f"asks: {bar.ask_budget.used}/{bar.ask_budget.max}"
        f" | validation: {bar.validation.verdict}{changed}"
        f" | approval: {bar.approval}"
        f" | insurer: {bar.insurer.stage}{ref}",
        f"context: {bar.context.uncompressed_tool_results}/{bar.context.threshold}"
        " uncompressed tool results",
    ]
    return "\n".join(lines)
