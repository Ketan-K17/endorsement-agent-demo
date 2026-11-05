"""Everything a tool can touch for one case: its event stream, the mock world, uploads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from endorsement_agent.case_file import CaseFile
from endorsement_agent.event_store import EventStore
from endorsement_agent.events import CaseEvent, DocumentUploaded, ExtractedField
from endorsement_agent.mock_world.insurer import InsurerStep, MockInsurer
from endorsement_agent.mock_world.policies import PolicyStore
from endorsement_agent.mock_world.rules import RulesMaster
from endorsement_agent.skills import SkillLibrary

TIMEZONE = ZoneInfo("Asia/Kolkata")  # the customers' and insurers' calendar


class Upload(BaseModel):
    doc_id: str
    filename: str
    mime: str
    data: bytes


class Classification(BaseModel):
    doc_type: str  # a rules-master doc type, or "other"
    quality: Literal["ok", "poor", "unreadable"]
    note: str | None = None


class VisionError(Exception):
    """The vision model could not read the document."""


class Vision(Protocol):
    """Document reading on the extractor role. Implemented in build step 4."""

    async def classify(self, upload: Upload, doc_types: list[str]) -> Classification: ...

    async def extract(
        self, upload: Upload, doc_type: str, fields: list[str]
    ) -> dict[str, ExtractedField]: ...


class Checker(Protocol):
    """The LLM pass of `validate_case` (ADR-0017): issues the deterministic checks can't see."""

    async def check(self, facts: str, previous: list[str]) -> list[str]: ...


@dataclass
class Runtime:
    case_id: str
    store: EventStore
    policies: PolicyStore
    rules: RulesMaster
    insurer: MockInsurer
    skills: SkillLibrary
    vision: Vision
    insurer_script: list[InsurerStep] | None = None  # per eval scenario; None = default
    checker: Checker | None = None  # None skips the LLM pass (unit tests)
    fixed_today: date | None = None  # for demos and evals (FIXED_TODAY); None = the real date
    uploads: dict[str, Upload] = field(default_factory=dict)

    def today(self) -> date:
        return self.fixed_today or datetime.now(TIMEZONE).date()

    @property
    def case(self) -> CaseFile:
        return self.store.case(self.case_id)

    def events(self) -> list[CaseEvent]:
        return self.store.events(self.case_id)

    def emit(self, event: CaseEvent) -> CaseFile:
        return self.store.append(self.case_id, event)

    def add_upload(self, filename: str, mime: str, data: bytes) -> Upload:
        upload = Upload(
            doc_id=f"doc_{len(self.uploads) + 1}", filename=filename, mime=mime, data=data
        )
        self.uploads[upload.doc_id] = upload
        self.emit(DocumentUploaded(doc_id=upload.doc_id, filename=filename))
        return upload
