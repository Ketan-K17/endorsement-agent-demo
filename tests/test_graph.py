from __future__ import annotations

import re
from datetime import date
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from endorsement_agent.config import Limits
from endorsement_agent.events import (
    ContextCompressed,
    ExtractedField,
    ImageStubbed,
    ModelCalled,
    ToolCalled,
    ToolResultAdded,
)
from endorsement_agent.graph import Agent, build_graph
from endorsement_agent.runtime import Classification, Runtime
from endorsement_agent.skills import SkillLibrary
from tests.fakes import FakeVision, ScriptedModel, call, calls, runtime
from tests.test_tools import owner_transfer_ready


async def no_compress(tool: str, args: dict[str, Any], content: str) -> str:
    return "stub"


@pytest.fixture
def rt() -> Runtime:
    return runtime(SkillLibrary())


def agent(rt: Runtime, script: list[AIMessage], **limits: int) -> tuple[Agent, ScriptedModel]:
    model = ScriptedModel(script=script)
    graph = build_graph(rt, model, no_compress, Limits(**limits))
    return Agent(rt, graph, callbacks=[]), model


async def test_a_fixed_today_reaches_the_status_bar(rt: Runtime) -> None:
    rt.fixed_today = date(2026, 10, 15)
    a, model = agent(rt, [AIMessage(content="Hello!")])
    await a.send("hi")
    assert str(model.prompts[0][-1].content).startswith("[STATUS] today=2026-10-15 ")


async def test_plain_reply_ends_turn_and_bar_is_last_not_stored(rt: Runtime) -> None:
    a, model = agent(rt, [AIMessage(content="Hello! Which policy?")])
    result = await a.send("hi")
    assert result.reply == "Hello! Which policy?" and result.approval is None
    [prompt] = model.prompts
    assert isinstance(prompt[0], SystemMessage) and "# SOP" in str(prompt[0].content)
    assert isinstance(prompt[-1], HumanMessage)
    assert re.match(r"\[STATUS\] today=\d{4}-\d\d-\d\d stage=Intake", str(prompt[-1].content))
    assert not any("[STATUS]" in str(m.content) for m in a.messages())


async def test_parallel_calls_then_reply(rt: Runtime) -> None:
    a, model = agent(
        rt,
        [
            calls(
                call("lookup_policy", "c1", policy_no="NWG-MOT-240117"),
                call("record_change_request", "c2", type="change-of-owner"),
            ),
            AIMessage(content="Found it."),
        ],
    )
    assert (await a.send("transfer NWG-MOT-240117")).reply == "Found it."
    tool_msgs = [m for m in a.messages() if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tool_msgs] == ["c1", "c2"]
    assert rt.case.policy is not None and rt.case.change_request is not None
    # the second call sees the updated status bar
    assert "stage=Docs" in str(model.prompts[1][-1].content)
    assert rt.case.context.uncompressed_tool_results == 1  # the change-request ack is short


async def test_approval_interrupts_and_resumes_without_rerunning(rt: Runtime) -> None:
    await owner_transfer_ready(rt)
    a, _ = agent(
        rt,
        [
            calls(call("validate_case", "v1")),
            calls(call("get_case", "g1"), call("request_approval", "a1", summary="transfer")),
            AIMessage(content="Approved; submitting next."),
        ],
    )
    paused = await a.send("go ahead")
    assert paused.reply is None and paused.approval is not None
    assert paused.approval["summary"] == "transfer"
    assert rt.case.approval.status == "pending"
    done = await a.resume({"decision": "approved"})
    assert done.reply == "Approved; submitting next."
    assert rt.case.approval.status == "approved"
    events = rt.events()
    assert sum(e.type == "approval.requested" for e in events) == 1
    results = [e for e in events if isinstance(e, ToolResultAdded)]
    assert [e.call_id for e in results].count("g1") == 1
    assert [m for m in a.messages() if isinstance(m, ToolMessage)][-1].content == "approved"


async def test_changes_requested_returns_reason(rt: Runtime) -> None:
    await owner_transfer_ready(rt)
    a, _ = agent(
        rt,
        [
            calls(call("validate_case", "v1"), call("request_approval", "a1", summary="s")),
            AIMessage(content="Will fix."),
        ],
    )
    await a.send("go")
    await a.resume({"decision": "changes_requested", "reason": "wrong phone"})
    assert rt.case.approval.status == "rejected"
    assert rt.case.approval.reason == "changes requested: wrong phone"


async def test_tool_call_cap_refuses_excess_and_forces_reply(rt: Runtime) -> None:
    a, model = agent(
        rt,
        [
            calls(call("get_case", "c1"), call("get_case", "c2"), call("get_case", "c3")),
            AIMessage(content="Done."),
        ],
        max_tool_calls_per_turn=2,
    )
    await a.send("hi")
    contents = [str(m.content) for m in a.messages() if isinstance(m, ToolMessage)]
    assert contents[2].startswith("refused: tool-call cap (2)")
    assert model.call_kwargs[0].get("tool_choice_marker") is None
    assert model.call_kwargs[1]["tool_choice_marker"] == "none"
    assert "tool-call cap" not in str(model.prompts[0][-1].content)
    assert "turn: tool-call cap reached (2/2)" in str(model.prompts[1][-1].content)


async def test_compression_runs_in_loop(rt: Runtime) -> None:
    a, _ = agent(
        rt,
        [
            calls(*(call("lookup_policy", f"c{i}", policy_no="NWG-MOT-240117") for i in range(5))),
            AIMessage(content="ok"),
        ],
    )
    await a.send("hi")
    [event] = [e for e in rt.events() if isinstance(e, ContextCompressed)]
    assert event.call_ids == ["c0", "c1", "c2", "c3"]
    contents = [str(m.content) for m in a.messages() if isinstance(m, ToolMessage)]
    assert all(c.startswith("[compressed #c") for c in contents[:4])
    assert not contents[4].startswith("[compressed")
    assert rt.case.context.uncompressed_tool_results == 1
    originals = {e.call_id: e.content for e in rt.events() if isinstance(e, ToolResultAdded)}
    assert originals["c0"].startswith("{")


async def test_image_stubbed_after_extraction(rt: Runtime) -> None:
    u = rt.add_upload("rc.jpg", "image/jpeg", b"img")
    assert isinstance(rt.vision, FakeVision)
    rt.vision.types[u.doc_id] = Classification(doc_type="rc", quality="ok")
    rt.vision.fields[u.doc_id] = {"reg_no": ExtractedField(value="KA05MZ4182", confidence=0.9)}
    a, model = agent(
        rt,
        [
            calls(call("classify_document", "k1", doc_id=u.doc_id)),
            calls(call("extract_fields", "e1", doc_id=u.doc_id, fields=["reg_no"])),
            AIMessage(content="Read your RC."),
        ],
    )
    await a.send("here is my RC", uploads=[u])
    upload_msg = next(m for m in a.messages() if m.id == f"upload-{u.doc_id}")
    stub = f"[image {u.doc_id} removed — fields in extract_fields({u.doc_id}) result]"
    assert upload_msg.content == stub
    assert isinstance(model.prompts[1][1].content, list)  # image still there before extraction
    assert [e.doc_id for e in rt.events() if isinstance(e, ImageStubbed)] == [u.doc_id]


async def test_skill_text_follows_results_as_user_message(rt: Runtime) -> None:
    a, model = agent(
        rt,
        [
            calls(call("load_skill", "s1", name="change-of-owner"), call("get_case", "g1")),
            calls(call("get_case", "g2")),
            AIMessage(content="ok"),
        ],
        max_tool_calls_per_turn=3,
    )
    await a.send("I sold my car")
    kinds = [(type(m).__name__, m.id) for m in a.messages()]
    assert kinds[2:5] == [
        ("ToolMessage", "tool-s1"),
        ("ToolMessage", "tool-g1"),
        ("HumanMessage", "skill-s1"),
    ]
    skill = a.messages()[4]
    assert str(skill.content).startswith("[skill change-of-owner]\n---")
    assert a.messages()[2].content == "loading skill change-of-owner"
    # attached skill text does not reset the per-turn cap: 3 calls used, so reply-only next
    assert model.call_kwargs[2]["tool_choice_marker"] == "none"
    [result] = [e for e in rt.events() if isinstance(e, ToolResultAdded) and e.call_id == "s1"]
    assert result.attachment == skill.content


async def test_a_turn_is_recorded_as_conversation_events(rt: Runtime) -> None:
    a, _ = agent(
        rt,
        [
            AIMessage(content="Looking.", tool_calls=[call("get_case", "g1")]),
            AIMessage(content="All clear."),
        ],
    )
    await a.send("status?")
    types = [e.type for e in rt.events()[1:]]
    assert types == [
        "message.user",
        "model.called",
        "message.assistant",
        "tool.called",
        "tool.result",
        "model.called",
        "message.assistant",
    ]
    [first, second] = [e for e in rt.events() if isinstance(e, ModelCalled)]
    assert (first.n_messages, first.tool_calls) == (1, 1)
    assert (second.n_messages, second.tool_calls) == (3, 0)


async def test_tool_called_is_not_repeated_on_resume(rt: Runtime) -> None:
    await owner_transfer_ready(rt)
    a, _ = agent(
        rt,
        [
            calls(call("validate_case", "v1"), call("request_approval", "a1", summary="s")),
            AIMessage(content="ok"),
        ],
    )
    await a.send("go")
    await a.resume({"decision": "approved"})
    called = [e.call_id for e in rt.events() if isinstance(e, ToolCalled)]
    assert called == ["v1", "a1"]


def marked(m: Any) -> bool:
    return isinstance(m.content, list) and "prompt_cache_breakpoint" in m.content[-1]


async def test_cache_breakpoints_keep_each_earlier_prompt_as_a_marked_prefix(
    rt: Runtime,
) -> None:
    model = ScriptedModel(
        script=[
            calls(call("get_case", "g1")),
            calls(call("get_case", "g2"), call("get_case", "g3")),
            AIMessage(content="Done."),
            AIMessage(content="Again."),
        ]
    )
    a = Agent(rt, build_graph(rt, model, no_compress, Limits(), cache_breakpoints=True), [])
    await a.send("hi")
    await a.send("and now?")
    prompts = model.prompts
    assert len(prompts) == 4
    for earlier, later in zip(prompts, prompts[1:], strict=False):
        # everything before the earlier bar is unchanged in the later call, marks included,
        # so the earlier call's last breakpoint matches the cache
        assert later[: len(earlier) - 1] == earlier[:-1]
        assert marked(earlier[-2])
    for p in prompts:
        assert marked(p[0]) and not marked(p[-1])  # system marked; the status bar never
        assert not any(marked(m) for m in p if isinstance(m, AIMessage))
    assert not any(marked(m) for m in a.messages())  # marks are never stored


async def test_no_breakpoints_by_default(rt: Runtime) -> None:
    a, model = agent(rt, [AIMessage(content="Hello!")])
    await a.send("hi")
    assert not any(marked(m) for m in model.prompts[0])
