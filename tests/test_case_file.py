from __future__ import annotations

import pytest

from endorsement_agent.case_file import apply, fold
from endorsement_agent.event_store import EventStore
from endorsement_agent.events import (
    CaseCreated,
    CaseEvent,
    ContextCompressed,
    DocumentReviewed,
    SkillLoaded,
    SlotRecorded,
    ToolResultAdded,
    event_adapter,
)
from tests.conftest import T0, Clock, owner_transfer_events


def test_fold_builds_case(clock: Clock) -> None:
    case = fold(owner_transfer_events(clock))
    assert case.case_id == "case-1"
    assert case.change_request is not None and case.change_request.type == "change-of-owner"
    assert [d.verdict for d in case.documents] == ["accepted", "rejected"]
    assert case.slots["chassis_no"].source == "doc:doc_1"


def test_fold_requires_case_created_first(clock: Clock) -> None:
    with pytest.raises(ValueError):
        fold(owner_transfer_events(clock)[1:])


def test_apply_is_pure(clock: Clock) -> None:
    case = fold(owner_transfer_events(clock))
    before = case.model_dump()
    apply(case, SkillLoaded(ts=clock(), name="document-triage"))
    assert case.model_dump() == before


def test_case_created_cannot_repeat(clock: Clock) -> None:
    case = fold(owner_transfer_events(clock))
    with pytest.raises(ValueError):
        apply(case, CaseCreated(ts=T0, case_id="case-1"))


def test_skill_loaded_once(clock: Clock) -> None:
    events = [*owner_transfer_events(clock), SkillLoaded(ts=clock(), name="change-of-owner")]
    assert fold(events).loaded_skills == ["change-of-owner"]


def test_superseded_slot_keeps_latest(clock: Clock) -> None:
    events = [
        *owner_transfer_events(clock),
        SlotRecorded(
            ts=clock(),
            name="chassis_no",
            value="MA1XX0001",
            source="user_msg",
            confidence=0.95,
            supersede_reason="user corrected OCR",
        ),
    ]
    slot = fold(events).slots["chassis_no"]
    assert (slot.value, slot.supersede_reason) == ("MA1XX0001", "user corrected OCR")


def test_context_counts_exclude_ask_user_and_compressed(clock: Clock) -> None:
    events: list[CaseEvent] = [CaseCreated(ts=T0, case_id="c", compress_threshold=5)]
    for i in range(5):
        events.append(ToolResultAdded(ts=clock(), tool="lookup_policy", call_id=f"r{i}"))
    events.append(ToolResultAdded(ts=clock(), tool="ask_user", call_id="ask"))
    assert fold(events).context.uncompressed_tool_results == 5

    compressed_at = clock()
    events.append(
        ContextCompressed(
            ts=compressed_at,
            call_ids=["r0", "r1", "r2", "r3"],
            tokens_before=4100,
            tokens_after=1200,
        )
    )
    ctx = fold(events).context
    assert (ctx.uncompressed_tool_results, ctx.last_compressed_at) == (1, compressed_at)


def test_store_assigns_seq_and_matches_fold(clock: Clock) -> None:
    first, *rest = owner_transfer_events(clock)
    assert isinstance(first, CaseCreated)
    store = EventStore()
    store.create(first)
    for e in rest:
        store.append("case-1", e)
    stream = store.events("case-1")
    assert [e.seq for e in stream] == list(range(1, len(rest) + 2))
    assert store.case("case-1") == fold(stream)
    assert [e.seq for e in store.events("case-1", after_seq=10)] == [11, 12]


def test_store_rejects_bad_event_without_storing(clock: Clock) -> None:
    store = EventStore()
    store.create(CaseCreated(ts=T0, case_id="c"))
    with pytest.raises(KeyError):
        store.append("c", DocumentReviewed(ts=clock(), doc_id="nope", verdict="accepted"))
    assert len(store.events("c")) == 1


def test_events_round_trip_json(clock: Clock) -> None:
    for e in owner_transfer_events(clock):
        assert event_adapter.validate_json(event_adapter.dump_json(e)) == e
