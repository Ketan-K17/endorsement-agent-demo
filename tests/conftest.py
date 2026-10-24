from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from endorsement_agent.events import (
    CaseCreated,
    CaseEvent,
    ChangeRequestRecorded,
    DocRequirement,
    DocumentClassified,
    DocumentReviewed,
    DocumentUploaded,
    PolicySelected,
    PolicySnapshot,
    Requirements,
    RulesLoaded,
    SkillLoaded,
    SlotRecorded,
    SlotRequirement,
)

T0 = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)


class Clock:
    """Deterministic timestamps: each call is one minute after the last."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> datetime:
        self.n += 1
        return T0 + timedelta(minutes=self.n)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def owner_transfer_events(clock: Clock) -> list[CaseEvent]:
    """A change-of-owner case with rules loaded, one doc accepted, one rejected."""
    return [
        CaseCreated(ts=T0, case_id="case-1"),
        PolicySelected(
            ts=clock(),
            policy=PolicySnapshot(
                policy_no="NWG-MOT-0001",
                insurer="Northwind General",
                reg_no="KA01AB1234",
                holder_name="Asha Rao",
            ),
        ),
        ChangeRequestRecorded(ts=clock(), change_type="change-of-owner"),
        SkillLoaded(ts=clock(), name="change-of-owner"),
        RulesLoaded(
            ts=clock(),
            requirements=Requirements(
                docs=[
                    DocRequirement(name="rc"),
                    DocRequirement(name="sale_deed"),
                    DocRequirement(name="noc", condition="only if the vehicle is hypothecated"),
                ],
                slots=[SlotRequirement(name="new_owner_name"), SlotRequirement(name="chassis_no")],
            ),
        ),
        DocumentUploaded(ts=clock(), doc_id="doc_1", filename="rc.jpg"),
        DocumentClassified(ts=clock(), doc_id="doc_1", doc_type="rc", quality="ok"),
        DocumentReviewed(ts=clock(), doc_id="doc_1", verdict="accepted"),
        DocumentUploaded(ts=clock(), doc_id="doc_2", filename="deed.jpg"),
        DocumentClassified(ts=clock(), doc_id="doc_2", doc_type="sale_deed", quality="poor"),
        DocumentReviewed(ts=clock(), doc_id="doc_2", verdict="rejected", reason="blurry"),
        SlotRecorded(
            ts=clock(), name="chassis_no", value="MA1XX0000", source="doc:doc_1", confidence=0.62
        ),
    ]
