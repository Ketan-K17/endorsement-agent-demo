"""The Case File: typed state of one case, folded from its events (DESIGN §3).

`apply` and `fold` are pure. Gates (confidence overwrite rules, approval before submit) are
enforced by the tools that emit events, not here; the fold records what happened.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

from endorsement_agent.events import (
    ApprovalDecided,
    ApprovalRequested,
    AskLogged,
    AssistantMessaged,
    CaseCreated,
    CaseEvent,
    ChangeRequestRecorded,
    ContextCompressed,
    DocumentClassified,
    DocumentExtracted,
    DocumentReviewed,
    DocumentUploaded,
    ExtractedField,
    HandoverRaised,
    ImageStubbed,
    InsurerResponded,
    InsurerSubmitted,
    InsurerUpdated,
    ModelCalled,
    PolicySelected,
    PolicySnapshot,
    Requirements,
    RequirementWaived,
    RulesLoaded,
    SkillLoaded,
    SlotRecorded,
    ToolCalled,
    ToolResultAdded,
    UserMessaged,
    ValidationCompleted,
    compressible,
)


class ChangeRequest(BaseModel):
    type: str
    details: dict[str, Any] = Field(default_factory=dict)


class Slot(BaseModel):
    """Current value of a slot. Earlier values stay in the event log."""

    value: str
    source: str
    confidence: float
    supersede_reason: str | None = None


class Doc(BaseModel):
    id: str
    filename: str
    type: str | None = None
    quality: Literal["ok", "poor", "unreadable"] | None = None
    extraction: dict[str, ExtractedField] | None = None
    verdict: Literal["accepted", "rejected"] | None = None
    verdict_reason: str | None = None


class Verdict(BaseModel):
    ts: AwareDatetime
    outcome: Literal["pass", "fail"]
    issues: list[str] = Field(default_factory=list)
    diff_vs_prev: list[str] = Field(default_factory=list)


class Ask(BaseModel):
    ts: AwareDatetime
    questions: list[str]
    reason: str


class Approval(BaseModel):
    status: Literal["none", "pending", "approved", "rejected"] = "none"
    summary: str | None = None
    reason: str | None = None


class Insurer(BaseModel):
    ref: str | None = None
    stage: Literal[
        "not_submitted", "submitted", "received", "query_raised", "approved", "issued", "rejected"
    ] = "not_submitted"
    last_message: str | None = None


class Handover(BaseModel):
    team: str
    reason: str
    severity: Literal["low", "medium", "high"]


class ContextState(BaseModel):
    uncompressed_tool_results: int = 0
    threshold: int = 5
    last_compressed_at: AwareDatetime | None = None


class CaseFile(BaseModel):
    case_id: str
    created_at: AwareDatetime
    ask_budget: int = 3
    policy: PolicySnapshot | None = None
    change_request: ChangeRequest | None = None
    requirements: Requirements | None = None
    waivers: dict[str, str] = Field(default_factory=dict)  # requirement name -> reason
    slots: dict[str, Slot] = Field(default_factory=dict)
    documents: list[Doc] = Field(default_factory=list)
    validation: list[Verdict] = Field(default_factory=list)
    asks: list[Ask] = Field(default_factory=list)
    approval: Approval = Field(default_factory=Approval)
    insurer: Insurer = Field(default_factory=Insurer)
    loaded_skills: list[str] = Field(default_factory=list)
    handover: Handover | None = None
    context: ContextState = Field(default_factory=ContextState)

    def doc(self, doc_id: str) -> Doc:
        for d in self.documents:
            if d.id == doc_id:
                return d
        raise KeyError(f"unknown document {doc_id}")


def apply(case: CaseFile, event: CaseEvent) -> CaseFile:
    """Return a new Case File with `event` applied. `case` is not modified."""
    c = case.model_copy(deep=True)
    match event:
        case CaseCreated():
            raise ValueError("case.created can only be the first event")
        case PolicySelected(policy=policy):
            c.policy = policy
        case ChangeRequestRecorded(change_type=t, details=details):
            c.change_request = ChangeRequest(type=t, details=details)
        case RulesLoaded(requirements=req):
            c.requirements = req
        case RequirementWaived(name=name, reason=reason):
            c.waivers[name] = reason
        case SlotRecorded():
            c.slots[event.name] = Slot(
                value=event.value,
                source=event.source,
                confidence=event.confidence,
                supersede_reason=event.supersede_reason,
            )
        case DocumentUploaded(doc_id=doc_id, filename=filename):
            c.documents.append(Doc(id=doc_id, filename=filename))
        case DocumentClassified(doc_id=doc_id, doc_type=doc_type, quality=quality):
            d = c.doc(doc_id)
            d.type, d.quality = doc_type, quality
        case DocumentExtracted(doc_id=doc_id, fields=fields):
            c.doc(doc_id).extraction = fields
        case DocumentReviewed(doc_id=doc_id, verdict=verdict, reason=reason):
            d = c.doc(doc_id)
            d.verdict, d.verdict_reason = verdict, reason
        case ValidationCompleted():
            c.validation.append(
                Verdict(
                    ts=event.ts,
                    outcome=event.outcome,
                    issues=event.issues,
                    diff_vs_prev=event.diff_vs_prev,
                )
            )
        case AskLogged(questions=questions, reason=reason):
            c.asks.append(Ask(ts=event.ts, questions=questions, reason=reason))
        case SkillLoaded(name=name):
            if name not in c.loaded_skills:
                c.loaded_skills.append(name)
        case ApprovalRequested(summary=summary):
            c.approval = Approval(status="pending", summary=summary)
        case ApprovalDecided(status=status, reason=reason):
            c.approval = Approval(status=status, summary=c.approval.summary, reason=reason)
        case InsurerSubmitted(ref=ref):
            c.insurer = Insurer(ref=ref, stage="submitted")
        case InsurerUpdated(stage=stage, message=message):
            c.insurer.stage, c.insurer.last_message = stage, message
        case HandoverRaised(team=team, reason=reason, severity=severity):
            c.handover = Handover(team=team, reason=reason, severity=severity)
        case ToolResultAdded(tool=tool, content=content):
            if compressible(tool, content):
                c.context.uncompressed_tool_results += 1
        case ContextCompressed(call_ids=call_ids):
            c.context.uncompressed_tool_results -= len(call_ids)
            c.context.last_compressed_at = event.ts
        case InsurerResponded() | ImageStubbed():
            pass  # audit only: the insurer stage moves on the next status check
        case UserMessaged() | AssistantMessaged() | ModelCalled() | ToolCalled():
            pass  # the conversation, for the UI, trace and evals
    return c


def fold(events: Iterable[CaseEvent]) -> CaseFile:
    """Build a Case File from its full event stream. The first event must be case.created."""
    it = iter(events)
    first = next(it, None)
    if not isinstance(first, CaseCreated):
        raise ValueError("event stream must start with case.created")
    case = CaseFile(
        case_id=first.case_id,
        created_at=first.ts,
        ask_budget=first.ask_budget,
        context=ContextState(threshold=first.compress_threshold),
    )
    for event in it:
        case = apply(case, event)
    return case
