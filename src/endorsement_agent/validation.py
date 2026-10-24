"""Deterministic case checks behind `validate_case` and `cross_check` (ADR-0015).

Issues come out in a fixed order, so the same case always gives the same verdict and the
diff against the previous verdict is stable across turns.
"""

from __future__ import annotations

import re
from typing import Literal

from endorsement_agent.case_file import CaseFile
from endorsement_agent.events import CaseEvent, ValidationCompleted
from endorsement_agent.status import LOW_CONFIDENCE, docs_checklist

Match = Literal["match", "partial", "mismatch"]

# Events that change what a verdict was computed on; any of them makes it stale.
_CHANGES = (
    "policy.selected",
    "change_request.recorded",
    "rules.loaded",
    "requirement.waived",
    "slot.recorded",
    "document.uploaded",
    "document.classified",
    "document.extracted",
    "document.reviewed",
)

# Extracted fields that must equal the policy's value when a document carries them.
_POLICY_KEYS = ("policy_no", "reg_no")


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[A-Z]+", s.upper()))


def compare(a: str, b: str) -> Match:
    """Identifiers match ignoring case and punctuation; names also ignoring word order.

    A name whose words are a subset of the other's ("Meera Shetty" vs "Meera R Shetty") is
    a partial match.
    """
    if norm(a) == norm(b):
        return "match"
    ta, tb = _tokens(a), _tokens(b)
    if ta and ta == tb:
        return "match"
    if ta and tb and (ta <= tb or tb <= ta):
        return "partial"
    return "mismatch"


def issues(case: CaseFile) -> list[str]:
    out: list[str] = []
    policy = case.policy
    if policy is None:
        out.append("no policy selected")
    elif policy.extra.get("status") == "lapsed":
        out.append("policy is lapsed")
    if case.change_request is None:
        out.append("no change request recorded")
    if case.requirements is None:
        out.append("rules not loaded")
        return out
    for check in docs_checklist(case):
        if check.state not in ("accepted", "waived"):
            out.append(f"doc {check.name} is {check.state}")
    for slot in case.requirements.slots:
        if slot.name not in case.waivers and slot.name not in case.slots:
            out.append(f"slot {slot.name} is missing")
    for name, value in sorted(case.slots.items()):
        if value.confidence < LOW_CONFIDENCE:
            out.append(f"slot {name} has low confidence ({value.confidence:.2f})")
    if policy is not None:
        for doc in case.documents:
            for key in _POLICY_KEYS:
                field = (doc.extraction or {}).get(key)
                expected = getattr(policy, key)
                if field and field.value and compare(field.value, expected) != "match":
                    out.append(f"{doc.id} {key} {field.value} does not match policy {expected}")
    return out


def diff(previous: list[str] | None, current: list[str]) -> list[str]:
    if previous is None:
        return []
    return [f"+ {i}" for i in current if i not in previous] + [
        f"- {i}" for i in previous if i not in current
    ]


def verdict_is_current(events: list[CaseEvent]) -> bool:
    """True when the latest validation passed and nothing it checked has changed since."""
    last_change = max((e.seq for e in events if e.type in _CHANGES), default=0)
    validations = [e for e in events if isinstance(e, ValidationCompleted)]
    if not validations:
        return False
    last = validations[-1]
    return last.outcome == "pass" and last.seq > last_change
