from __future__ import annotations

import pytest
from syrupy.assertion import SnapshotAssertion

from endorsement_agent.case_file import CaseFile, fold
from endorsement_agent.events import (
    ApprovalDecided,
    ApprovalRequested,
    AskLogged,
    CaseCreated,
    CaseEvent,
    DocumentClassified,
    DocumentReviewed,
    DocumentUploaded,
    HandoverRaised,
    InsurerSubmitted,
    InsurerUpdated,
    RequirementWaived,
    SlotRecorded,
    ValidationCompleted,
)
from endorsement_agent.status import render_status, stage, to_text
from tests.conftest import T0, Clock, owner_transfer_events


def _docs_complete(clock: Clock) -> list[CaseEvent]:
    """Owner transfer with every required doc accepted and both slots filled."""
    return [
        *owner_transfer_events(clock),
        DocumentUploaded(ts=clock(), doc_id="doc_3", filename="deed2.jpg"),
        DocumentClassified(ts=clock(), doc_id="doc_3", doc_type="sale_deed", quality="ok"),
        DocumentReviewed(ts=clock(), doc_id="doc_3", verdict="accepted"),
        DocumentUploaded(ts=clock(), doc_id="doc_4", filename="noc.pdf"),
        DocumentClassified(ts=clock(), doc_id="doc_4", doc_type="noc", quality="ok"),
        DocumentReviewed(ts=clock(), doc_id="doc_4", verdict="accepted"),
        SlotRecorded(
            ts=clock(),
            name="new_owner_name",
            value="Ravi Iyer",
            source="doc:doc_3",
            confidence=0.93,
        ),
        AskLogged(ts=clock(), questions=["Is the vehicle hypothecated?"], reason="noc condition"),
    ]


def _approved(clock: Clock) -> list[CaseEvent]:
    return [
        *_docs_complete(clock),
        ValidationCompleted(ts=clock(), outcome="fail", issues=["name mismatch on deed"]),
        ValidationCompleted(
            ts=clock(), outcome="pass", diff_vs_prev=["resolved: name mismatch on deed"]
        ),
        ApprovalRequested(ts=clock(), summary="Transfer KA01AB1234 to Ravi Iyer"),
        ApprovalDecided(ts=clock(), status="approved"),
    ]


def _case(name: str, clock: Clock) -> CaseFile:
    match name:
        case "new":
            return fold([CaseCreated(ts=T0, case_id="case-1")])
        case "docs":
            return fold(owner_transfer_events(clock))
        case "validate":
            return fold(_docs_complete(clock))
        case "approval_pending":
            events = _approved(clock)[:-1]
            return fold(events)
        case "insurer_query":
            return fold(
                [
                    *_approved(clock),
                    InsurerSubmitted(ts=clock(), ref="NWG-END-7781"),
                    InsurerUpdated(ts=clock(), stage="query_raised", message="seller NOC unclear"),
                ]
            )
        case "done":
            return fold(
                [
                    *_approved(clock),
                    InsurerSubmitted(ts=clock(), ref="NWG-END-7781"),
                    InsurerUpdated(ts=clock(), stage="issued"),
                ]
            )
        case "handover":
            return fold(
                [
                    *owner_transfer_events(clock),
                    HandoverRaised(
                        ts=clock(), team="fraud-review", reason="chassis mismatch", severity="high"
                    ),
                ]
            )
    raise AssertionError(name)


EXPECTED_STAGE = {
    "new": "Intake",
    "docs": "Docs",
    "validate": "Validate",
    "approval_pending": "Approval",
    "insurer_query": "Insurer",
    "done": "Done",
    "handover": "Handover",
}


@pytest.mark.parametrize("name", EXPECTED_STAGE)
def test_stage(name: str, clock: Clock) -> None:
    assert stage(_case(name, clock)) == EXPECTED_STAGE[name]


@pytest.mark.parametrize("name", EXPECTED_STAGE)
def test_render_text_snapshot(name: str, clock: Clock, snapshot: SnapshotAssertion) -> None:
    assert to_text(render_status(_case(name, clock))) == snapshot


@pytest.mark.parametrize("name", EXPECTED_STAGE)
def test_render_json_snapshot(name: str, clock: Clock, snapshot: SnapshotAssertion) -> None:
    assert render_status(_case(name, clock)).model_dump(mode="json") == snapshot


def test_rules_not_loaded_stays_in_docs(clock: Clock) -> None:
    events = owner_transfer_events(clock)[:4]  # change request recorded, no rules yet
    assert stage(fold(events)) == "Docs"


def test_rejection_keeps_approval_stage(clock: Clock) -> None:
    events = [*_approved(clock)[:-1], ApprovalDecided(ts=clock(), status="rejected", reason="x")]
    case = fold(events)
    assert (stage(case), render_status(case).approval) == ("Approval", "rejected")


def test_render_is_deterministic(clock: Clock) -> None:
    case = _case("insurer_query", clock)
    assert render_status(case) == render_status(case)


def test_waived_requirement_counts_as_satisfied(clock: Clock) -> None:
    events = [
        *_docs_complete(clock)[:-5],  # noc never uploaded
        RequirementWaived(ts=clock(), name="noc", reason="policy shows no financier"),
    ]
    case = fold(events)
    noc = next(c for c in render_status(case).docs_checklist if c.name == "noc")
    assert (noc.state, noc.reason) == ("waived", "policy shows no financier")
    assert stage(case) == "Validate"


def test_waived_slot_leaves_total(clock: Clock) -> None:
    events = [
        *owner_transfer_events(clock),
        RequirementWaived(ts=clock(), name="new_owner_name", reason="test"),
    ]
    assert render_status(fold(events)).slots.total == 1
