"""Case events: the single append-only stream behind the Case File (ADR-0008).

Case File events plus the history transforms (image stubbing, compression), which the
Context tab and evals replay. Model and UI events are added with the steps that emit them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, TypeAdapter

ASK_USER_TOOL = "ask_user"
# A tool result shorter than this is left as is: a stub would be no shorter (ADR-0015).
COMPRESS_MIN_CHARS = 400


def compressible(tool: str, content: str) -> bool:
    """Counts toward the compression trigger and can be compressed."""
    return tool != ASK_USER_TOOL and len(content) >= COMPRESS_MIN_CHARS


def _now() -> datetime:
    return datetime.now(UTC)


class PolicySnapshot(BaseModel):
    policy_no: str
    insurer: str
    reg_no: str
    holder_name: str
    nominee_name: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class DocRequirement(BaseModel):
    name: str
    condition: str | None = None


class SlotRequirement(BaseModel):
    name: str
    condition: str | None = None


class Requirements(BaseModel):
    docs: list[DocRequirement] = Field(default_factory=list)
    slots: list[SlotRequirement] = Field(default_factory=list)


class ExtractedField(BaseModel):
    value: str | None
    confidence: float = Field(ge=0.0, le=1.0)


class _Event(BaseModel):
    seq: int = 0
    ts: AwareDatetime = Field(default_factory=_now)


class CaseCreated(_Event):
    type: Literal["case.created"] = "case.created"
    case_id: str
    ask_budget: int = 3
    compress_threshold: int = 5


class PolicySelected(_Event):
    type: Literal["policy.selected"] = "policy.selected"
    policy: PolicySnapshot


class ChangeRequestRecorded(_Event):
    type: Literal["change_request.recorded"] = "change_request.recorded"
    change_type: str
    details: dict[str, Any] = Field(default_factory=dict)


class RulesLoaded(_Event):
    type: Literal["rules.loaded"] = "rules.loaded"
    requirements: Requirements


class RequirementWaived(_Event):
    """A conditional requirement does not apply. The tool refuses unconditional ones."""

    type: Literal["requirement.waived"] = "requirement.waived"
    name: str
    reason: str


class SlotRecorded(_Event):
    type: Literal["slot.recorded"] = "slot.recorded"
    name: str
    value: str
    source: str  # "user_msg" or "doc:<id>"
    confidence: float = Field(ge=0.0, le=1.0)
    supersede_reason: str | None = None


class DocumentUploaded(_Event):
    type: Literal["document.uploaded"] = "document.uploaded"
    doc_id: str
    filename: str


class DocumentClassified(_Event):
    type: Literal["document.classified"] = "document.classified"
    doc_id: str
    doc_type: str
    quality: Literal["ok", "poor", "unreadable"]


class DocumentExtracted(_Event):
    type: Literal["document.extracted"] = "document.extracted"
    doc_id: str
    fields: dict[str, ExtractedField]


class DocumentReviewed(_Event):
    type: Literal["document.reviewed"] = "document.reviewed"
    doc_id: str
    verdict: Literal["accepted", "rejected"]
    reason: str | None = None


class ValidationCompleted(_Event):
    type: Literal["validation.completed"] = "validation.completed"
    outcome: Literal["pass", "fail"]
    issues: list[str] = Field(default_factory=list)
    diff_vs_prev: list[str] = Field(default_factory=list)


class AskLogged(_Event):
    type: Literal["ask.logged"] = "ask.logged"
    questions: list[str]
    reason: str


class SkillLoaded(_Event):
    type: Literal["skill.loaded"] = "skill.loaded"
    name: str


class ApprovalRequested(_Event):
    type: Literal["approval.requested"] = "approval.requested"
    summary: str


class ApprovalDecided(_Event):
    type: Literal["approval.decided"] = "approval.decided"
    status: Literal["approved", "rejected"]
    reason: str | None = None


class InsurerSubmitted(_Event):
    type: Literal["insurer.submitted"] = "insurer.submitted"
    ref: str


class InsurerUpdated(_Event):
    type: Literal["insurer.updated"] = "insurer.updated"
    stage: Literal["received", "query_raised", "approved", "issued", "rejected"]
    message: str | None = None


class InsurerResponded(_Event):
    """An answer sent to an open insurer query (ADR-0014). Kept for eval assertions."""

    type: Literal["insurer.responded"] = "insurer.responded"
    message: str
    doc_ids: list[str] = Field(default_factory=list)


class HandoverRaised(_Event):
    type: Literal["handover.raised"] = "handover.raised"
    team: str
    reason: str
    severity: Literal["low", "medium", "high"]


class ToolResultAdded(_Event):
    """A tool result entered the trajectory. Feeds the context meter."""

    type: Literal["tool.result"] = "tool.result"
    tool: str
    call_id: str
    content: str = ""  # the original result, kept after compression (DESIGN §6)
    attachment: str | None = None  # skill text sent as a user message after the results


class ContextCompressed(_Event):
    type: Literal["context.compressed"] = "context.compressed"
    call_ids: list[str]
    tokens_before: int
    tokens_after: int
    stubs: dict[str, str] = Field(default_factory=dict)  # call_id -> stub that replaced it


class ImageStubbed(_Event):
    """An upload's image part was replaced by a text stub after extraction (DESIGN §6.1)."""

    type: Literal["history.image_stubbed"] = "history.image_stubbed"
    doc_id: str


CaseEvent = Annotated[
    CaseCreated
    | PolicySelected
    | ChangeRequestRecorded
    | RulesLoaded
    | RequirementWaived
    | SlotRecorded
    | DocumentUploaded
    | DocumentClassified
    | DocumentExtracted
    | DocumentReviewed
    | ValidationCompleted
    | AskLogged
    | SkillLoaded
    | ApprovalRequested
    | ApprovalDecided
    | InsurerSubmitted
    | InsurerUpdated
    | InsurerResponded
    | HandoverRaised
    | ToolResultAdded
    | ContextCompressed
    | ImageStubbed,
    Field(discriminator="type"),
]

event_adapter: TypeAdapter[CaseEvent] = TypeAdapter(CaseEvent)
