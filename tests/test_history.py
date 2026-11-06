from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from endorsement_agent.case_file import CaseFile, apply
from endorsement_agent.events import (
    DocumentClassified,
    DocumentExtracted,
    DocumentUploaded,
    ExtractedField,
    ToolResultAdded,
)
from endorsement_agent.history import LLMCompressor, compress, stub_images, upload_message
from endorsement_agent.runtime import Upload
from endorsement_agent.skills import SkillLibrary
from tests.fakes import ScriptedModel, runtime


async def echo(tool: str, args: dict[str, Any], content: str) -> str:
    return f"short {content.split()[1]}"


def trajectory(names: list[str]) -> list[BaseMessage]:
    """One assistant message calling `names` in parallel, then their results."""
    ids = [f"c{i}" for i in range(len(names))]
    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": n, "args": {"i": i}, "id": c}
            for i, (n, c) in enumerate(zip(names, ids, strict=True))
        ],
    )
    results: list[BaseMessage] = [
        ToolMessage(id=f"tool-{c}", tool_call_id=c, name=n, content=f"result {c} " * 50)
        for n, c in zip(names, ids, strict=True)
    ]
    return [HumanMessage("hi"), ai, *results]


def counted_case(names: list[str]) -> CaseFile:
    rt = runtime(SkillLibrary())
    for i, n in enumerate(names):
        rt.emit(ToolResultAdded(tool=n, call_id=f"c{i}", content="x" * 500))
    return rt.case


async def test_below_threshold_nothing_happens() -> None:
    names = ["get_case"] * 4
    assert await compress(trajectory(names), counted_case(names), set(), echo) is None


async def test_compresses_all_but_latest_and_skips_ask_acks() -> None:
    names = ["get_case", "ask_user", "lookup_policy", "get_case", "list_documents", "get_case"]
    case = counted_case(names)
    assert case.context.uncompressed_tool_results == 5
    result = await compress(trajectory(names), case, set(), echo)
    assert result is not None
    stubs, event = result
    assert event.call_ids == ["c0", "c2", "c3", "c4"]  # c1 is an ask ack, c5 the latest
    assert stubs[0].id == "tool-c0" and stubs[0].tool_call_id == "c0"
    assert str(stubs[0].content).startswith('[compressed #c0 get_case({"i": 0}): short c0')
    assert event.tokens_after < event.tokens_before
    assert apply(case, event).context.uncompressed_tool_results == 1


async def test_never_recompresses() -> None:
    names = ["get_case"] * 6
    case = counted_case(names)
    result = await compress(trajectory(names), case, {"c0", "c1", "c2", "c3", "c4"}, echo)
    assert result is None


def test_stub_images_after_classify_and_extract() -> None:
    rt = runtime(SkillLibrary())
    msg = upload_message(Upload(doc_id="doc_1", filename="rc.jpg", mime="image/jpeg", data=b"x"))
    rt.emit(DocumentUploaded(doc_id="doc_1", filename="rc.jpg"))
    rt.emit(DocumentClassified(doc_id="doc_1", doc_type="rc", quality="ok"))
    assert stub_images([msg], rt.case) == []
    fields = {"reg_no": ExtractedField(value="KA05MZ4182", confidence=0.9)}
    rt.emit(DocumentExtracted(doc_id="doc_1", fields=fields))
    [stub] = stub_images([msg], rt.case)
    assert stub.id == "upload-doc_1"
    assert stub.content == "[image doc_1 removed — fields in extract_fields(doc_1) result]"
    assert stub_images([stub], rt.case) == []  # already stubbed


async def test_llm_compressor_sends_rules_and_hint() -> None:
    model = ScriptedModel(script=[AIMessage(content=" policy NWG-MOT-240117 ")])
    out = await LLMCompressor(model)("lookup_policy", {"policy_no": "x"}, "{...}")
    assert out == " policy NWG-MOT-240117 "
    system, user = model.prompts[0]
    assert "Keep every identifier" in str(system.content) and "financier" in str(system.content)
    assert "tool: lookup_policy" in str(user.content)


async def test_short_results_count_as_already_compressed() -> None:
    names = ["get_case"] * 6
    messages = trajectory(names)
    short = messages[2]
    assert isinstance(short, ToolMessage)
    messages[2] = ToolMessage(id=short.id, tool_call_id="c0", name="get_case", content="ok")
    case = counted_case(names[1:])  # five long results counted
    result = await compress(messages, case, set(), echo)
    assert result is not None
    assert result[1].call_ids == ["c1", "c2", "c3", "c4"]  # c0 is short, c5 the latest
