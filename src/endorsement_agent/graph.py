"""The agent loop: one agent node, one tool node (DESIGN §2, ADR-0001).

The prompt is system (role + guidelines + SOP) → tool definitions → full history → status
bar. The bar is built per call and never enters the state or the checkpoint.
A turn ends on an assistant message with no tool calls (ADR-0010).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from endorsement_agent import tools
from endorsement_agent.config import Limits
from endorsement_agent.events import ContextCompressed, ImageStubbed, ToolResultAdded
from endorsement_agent.history import (
    SKILL_PREFIX,
    Compressor,
    compress,
    stub_images,
    upload_message,
)
from endorsement_agent.runtime import Runtime, Upload
from endorsement_agent.status import render_status, to_text

SYSTEM_PROMPT = (Path(__file__).parent / "sop.md").read_text()


def tool_calls_this_turn(messages: Sequence[BaseMessage]) -> int:
    """Tool calls made since the last user message (attached skill text does not count)."""
    count = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and not (m.id or "").startswith(SKILL_PREFIX):
            break
        if isinstance(m, AIMessage):
            count += len(m.tool_calls)
    return count


def model_input(messages: Sequence[BaseMessage], rt: Runtime) -> list[BaseMessage]:
    """What one model call sees. The status bar goes last and is not stored."""
    bar = HumanMessage(to_text(render_status(rt.case, rt.today())))
    return [SystemMessage(SYSTEM_PROMPT), *messages, bar]


def build_graph(
    rt: Runtime,
    model: BaseChatModel,
    compressor: Compressor,
    limits: Limits,
    checkpointer: InMemorySaver | None = None,
) -> CompiledStateGraph[Any]:
    definitions = tools.definitions(rt.skills)
    with_tools = model.bind_tools(definitions)
    # Past the per-turn cap the model keeps its tool definitions (cache) but must reply.
    reply_only = model.bind_tools(definitions, tool_choice="none")

    async def agent(state: MessagesState) -> dict[str, list[BaseMessage]]:
        messages = state["messages"]
        capped = tool_calls_this_turn(messages) >= limits.max_tool_calls_per_turn
        reply = await (reply_only if capped else with_tools).ainvoke(model_input(messages, rt))
        return {"messages": [reply]}

    async def run_call(
        call: dict[str, Any], done: dict[str, ToolResultAdded], allowed: bool
    ) -> tuple[ToolMessage, HumanMessage | None]:
        """The tool message, plus skill text to attach as a user message."""
        if call["id"] in done:  # already ran before an approval interrupt; do not repeat
            out = tools.ToolOutput(done[call["id"]].content, done[call["id"]].attachment)
        else:
            if allowed:
                out = await tools.call(rt, call["name"], call["args"])
            else:
                out = tools.ToolOutput(
                    f"refused: tool-call cap ({limits.max_tool_calls_per_turn}) for this turn "
                    "reached; reply to the user now"
                )
            rt.emit(
                ToolResultAdded(
                    tool=call["name"],
                    call_id=call["id"],
                    content=out.text,
                    attachment=out.attachment,
                )
            )
        message = ToolMessage(
            id=f"tool-{call['id']}", tool_call_id=call["id"], name=call["name"], content=out.text
        )
        attached = None
        if out.attachment is not None:
            attached = HumanMessage(id=f"{SKILL_PREFIX}{call['id']}", content=out.attachment)
        return message, attached

    async def tool_node(state: MessagesState) -> dict[str, list[BaseMessage]]:
        messages = state["messages"]
        last = messages[-1]
        assert isinstance(last, AIMessage)
        events = rt.events()
        done = {e.call_id: e for e in events if isinstance(e, ToolResultAdded)}
        budget = limits.max_tool_calls_per_turn - tool_calls_this_turn(messages[:-1])
        calls = [dict(c) for c in last.tool_calls]
        allowed = {c["id"]: i < budget for i, c in enumerate(calls)}
        # Parallel calls run concurrently; an approval waits for them, then interrupts.
        parallel = [c for c in calls if c["name"] != tools.APPROVAL_TOOL]
        results = dict(
            zip(
                [c["id"] for c in parallel],
                await asyncio.gather(*(run_call(c, done, allowed[c["id"]]) for c in parallel)),
                strict=True,
            )
        )
        for c in calls:
            if c["name"] == tools.APPROVAL_TOOL:
                results[c["id"]] = await run_call(c, done, allowed[c["id"]])
        new: list[BaseMessage] = [results[c["id"]][0] for c in calls]
        # Tool results must directly follow the calls; attached skill text comes after them.
        attached = [a for c in calls if (a := results[c["id"]][1]) is not None]
        older = await _transform([*messages, *new], new)  # may replace items of `new`
        return {"messages": [*new, *attached, *older]}

    async def _transform(messages: list[BaseMessage], new: list[BaseMessage]) -> list[BaseMessage]:
        """Stub images and compress. Replaces in `new` in place; returns older replacements."""
        replacements: dict[str | None, BaseMessage] = {}
        for m in stub_images(messages, rt.case):
            rt.emit(ImageStubbed(doc_id=(m.id or "").removeprefix("upload-")))
            replacements[m.id] = m
        already = {
            cid for e in rt.events() if isinstance(e, ContextCompressed) for cid in e.call_ids
        }
        current = [replacements.get(m.id, m) for m in messages]
        compressed = await compress(current, rt.case, already, compressor)
        if compressed:
            stubs, event = compressed
            rt.emit(event)
            replacements.update({m.id: m for m in stubs})
        # A replacement of a message added in this same update is applied in place there.
        for i, added in enumerate(new):
            if added.id in replacements:
                new[i] = replacements.pop(added.id)
        return list(replacements.values())

    def route(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


@dataclass
class TurnResult:
    reply: str | None  # the final assistant message; None while waiting for approval
    approval: dict[str, Any] | None  # the interrupt payload when the graph paused for approval


class Agent:
    """One case's conversation: send user turns, resume after an approval decision."""

    def __init__(self, rt: Runtime, graph: CompiledStateGraph[Any], callbacks: list[Any]) -> None:
        self.rt = rt
        self.graph = graph
        self.config: RunnableConfig = {
            "configurable": {"thread_id": rt.case_id},
            "callbacks": callbacks,
            "metadata": {"langfuse_session_id": rt.case_id},
        }

    async def send(self, text: str, uploads: list[Upload] | None = None) -> TurnResult:
        messages: list[BaseMessage] = [upload_message(u) for u in uploads or []]
        messages.append(HumanMessage(text))
        return await self._run({"messages": messages})

    async def resume(self, decision: dict[str, Any]) -> TurnResult:
        return await self._run(Command(resume=decision))

    async def _run(self, payload: dict[str, Any] | Command[Any]) -> TurnResult:
        state = await self.graph.ainvoke(payload, self.config)
        if pending := state.get("__interrupt__"):
            return TurnResult(reply=None, approval=pending[0].value)
        last = state["messages"][-1]
        return TurnResult(reply=str(last.content), approval=None)

    def messages(self) -> list[BaseMessage]:
        snapshot = self.graph.get_state(self.config)
        return list(snapshot.values.get("messages", []))
