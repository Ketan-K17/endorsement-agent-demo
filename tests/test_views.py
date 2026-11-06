from __future__ import annotations

from langchain_core.messages import AIMessage

from endorsement_agent.case_file import fold
from endorsement_agent.events import (
    CaseCreated,
    ExtractedField,
    InsurerSubmitted,
    InsurerUpdated,
    PolicySelected,
    PolicySnapshot,
)
from endorsement_agent.runtime import Classification, Runtime
from endorsement_agent.skills import SkillLibrary
from endorsement_agent.views import (
    assignee,
    context_log,
    current_activity,
    trace_view,
    ui_status,
)
from tests.fakes import FakeVision, call, calls, runtime
from tests.test_graph import agent


def rt() -> Runtime:
    return runtime(SkillLibrary())


async def test_old_status_bars_are_out_of_the_prompt_and_the_next_one_is_in() -> None:
    r = rt()
    a, model = agent(r, [calls(call("get_case", "g1")), AIMessage(content="Done.")])
    await a.send("hi")
    items = context_log(a.messages(), r.events(), r.today())
    assert items[0].kind == "system" and items[0].in_prompt
    bars = [i for i in items if i.kind == "status"]
    assert [b.in_prompt for b in bars] == [False, False, True]
    # each old bar is what that call saw, placed right after the history it followed
    assert [b.text for b in bars[:2]] == [str(p[-1].content) for p in model.prompts]
    kinds = [i.kind for i in items]
    assert kinds == [
        "system",
        "user",
        "status",
        "assistant",
        "tool",
        "status",
        "assistant",
        "status",
    ]


async def test_compressed_results_show_the_original_out_and_the_stub_in() -> None:
    r = rt()
    a, _ = agent(
        r,
        [
            calls(*(call("lookup_policy", f"c{i}", policy_no="NWG-MOT-240117") for i in range(5))),
            AIMessage(content="ok"),
        ],
    )
    await a.send("hi")
    tools = [i for i in context_log(a.messages(), r.events(), r.today()) if i.kind == "tool"]
    assert len(tools) == 9  # four originals out + four stubs in + the latest raw result
    assert tools[0].in_prompt is False and tools[0].text.startswith("{")
    assert tools[1].in_prompt and tools[1].text.startswith("[compressed #c0")
    assert tools[1].note == "lookup_policy, compressed"
    assert tools[-1].in_prompt and tools[-1].text.startswith("{")


async def test_a_stubbed_image_shows_the_upload_out_and_the_stub_in() -> None:
    r = rt()
    u = r.add_upload("rc.jpg", "image/jpeg", b"img")
    assert isinstance(r.vision, FakeVision)
    r.vision.types[u.doc_id] = Classification(doc_type="rc", quality="ok")
    r.vision.fields[u.doc_id] = {"reg_no": ExtractedField(value="KA05MZ4182", confidence=0.9)}
    a, _ = agent(
        r,
        [
            calls(call("classify_document", "k1", doc_id=u.doc_id)),
            calls(call("extract_fields", "e1", doc_id=u.doc_id, fields=["reg_no"])),
            AIMessage(content="Read your RC."),
        ],
    )
    await a.send("here is my RC", uploads=[u])
    uploads = [i for i in context_log(a.messages(), r.events(), r.today()) if i.kind == "upload"]
    assert [(i.in_prompt, i.text) for i in uploads] == [
        (False, f"[uploaded {u.doc_id}: rc.jpg] + image"),
        (True, f"[image {u.doc_id} — see extraction above]"),
    ]


async def test_trace_view_and_activity_come_from_events() -> None:
    r = rt()
    a, _ = agent(
        r, [calls(call("get_case", "g1"), call("get_case", "g2")), AIMessage(content="ok")]
    )
    await a.send("hi")
    t = trace_view(r.events())
    assert (t.model_calls, t.tool_calls) == (2, 2)
    assert current_activity(r.events(), busy=True, awaiting_approval=False) == "thinking"
    assert current_activity(r.events(), busy=False, awaiting_approval=False) == "idle"
    assert (
        current_activity(r.events(), busy=False, awaiting_approval=True) == "waiting for approval"
    )
    status = ui_status(r.case, r.events(), r.today(), busy=False, awaiting_approval=False)
    assert status["stage"] == "Intake" and status["trace_view"]["tool_calls"] == 2
    assert status["assignee"] == {"role": "customer", "name": None}


def test_assignee_follows_whose_move_it_is() -> None:
    policy = PolicySnapshot(
        policy_no="NWG-MOT-240117",
        insurer="Northwind General",
        reg_no="KA05MZ4182",
        holder_name="A. Rao",
    )
    events = [CaseCreated(case_id="c"), PolicySelected(policy=policy)]
    case = fold(events)
    assert assignee(case, busy=False, awaiting_approval=False).role == "customer"
    assert assignee(case, busy=True, awaiting_approval=False).role == "agent"
    assert assignee(case, busy=False, awaiting_approval=True).role == "approver"
    submitted = fold([*events, InsurerSubmitted(ref="R1")])
    assert assignee(submitted, busy=False, awaiting_approval=False).model_dump() == {
        "role": "insurer",
        "name": "Northwind General",
    }
    assert assignee(submitted, busy=True, awaiting_approval=False).role == "agent"
    query = fold([*events, InsurerSubmitted(ref="R1"), InsurerUpdated(stage="query_raised")])
    assert assignee(query, busy=False, awaiting_approval=False).role == "customer"
    issued = fold([*events, InsurerSubmitted(ref="R1"), InsurerUpdated(stage="issued")])
    assert assignee(issued, busy=False, awaiting_approval=False).role == "customer"
