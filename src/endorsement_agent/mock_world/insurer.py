"""Mock insurer: a scripted state machine per submission (DESIGN §4).

Each `status` poll advances one step. A `query_raised` step holds until `respond` is called;
the next poll then moves on. The last step repeats once reached.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

InsurerStage = Literal["received", "query_raised", "approved", "issued", "rejected"]

PREFIX = {"Northwind General": "NWG", "Cedar Mutual": "CDM", "Halcyon Assurance": "HLA"}


class InsurerStep(BaseModel):
    stage: InsurerStage
    message: str | None = None


DEFAULT_SCRIPT = [
    InsurerStep(stage="received"),
    InsurerStep(stage="approved"),
    InsurerStep(stage="issued", message="Endorsement issued."),
]


class Submission(BaseModel):
    ref: str
    case_id: str
    insurer: str
    script: list[InsurerStep]
    position: int = -1
    responses: list[str] = Field(default_factory=list)
    awaiting_response: bool = False


class MockInsurer:
    def __init__(self) -> None:
        self._by_ref: dict[str, Submission] = {}
        self._by_case: dict[str, str] = {}

    def submit(self, case_id: str, insurer: str, script: list[InsurerStep] | None = None) -> str:
        """Return the submission ref. Idempotent per case: a repeat returns the same ref."""
        if case_id in self._by_case:
            return self._by_case[case_id]
        ref = f"{PREFIX[insurer]}-END-{len(self._by_ref) + 1:04d}"
        steps = list(DEFAULT_SCRIPT if script is None else script)
        if not steps:
            raise ValueError("insurer script is empty")
        self._by_ref[ref] = Submission(ref=ref, case_id=case_id, insurer=insurer, script=steps)
        self._by_case[case_id] = ref
        return ref

    def status(self, ref: str) -> InsurerStep:
        sub = self._by_ref[ref]
        if not sub.awaiting_response and sub.position < len(sub.script) - 1:
            sub.position += 1
            sub.awaiting_response = sub.script[sub.position].stage == "query_raised"
        return sub.script[sub.position]

    def respond(self, ref: str, message: str) -> None:
        sub = self._by_ref[ref]
        if not sub.awaiting_response:
            raise ValueError(f"{ref} has no open query")
        sub.responses.append(message)
        sub.awaiting_response = False

    def submission(self, ref: str) -> Submission:
        return self._by_ref[ref]
