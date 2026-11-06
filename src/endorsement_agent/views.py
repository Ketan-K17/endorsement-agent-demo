"""What the UI shows, derived from the event stream. Pure functions, no I/O.

The UI status bar adds `current_activity`, `trace_view` and `assignee` to `render_status`
(ADR-0013).
The Context tab lists every message the model has seen, marking what is still in the prompt.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from endorsement_agent.case_file import CaseFile, fold
from endorsement_agent.events import (
    CaseEvent,
    ContextCompressed,
    DocumentUploaded,
    ImageStubbed,
    ModelCalled,
    ToolCalled,
    ToolResultAdded,
)
from endorsement_agent.graph import SYSTEM_PROMPT, text_of
from endorsement_agent.history import SKILL_PREFIX, UPLOAD_PREFIX
from endorsement_agent.status import render_status, to_text


class TraceView(BaseModel):
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_ms: int = 0


def trace_view(events: Sequence[CaseEvent]) -> TraceView:
    """Totals for the in-app trace view (ADR-0009)."""
    t = TraceView()
    for e in events:
        if isinstance(e, ModelCalled):
            t.model_calls += 1
            t.input_tokens += e.input_tokens or 0
            t.output_tokens += e.output_tokens or 0
            t.model_ms += e.duration_ms
        elif isinstance(e, ToolCalled):
            t.tool_calls += 1
    return t


def current_activity(events: Sequence[CaseEvent], busy: bool, awaiting_approval: bool) -> str:
    if awaiting_approval:
        return "waiting for approval"
    if not busy:
        return "idle"
    done = {e.call_id for e in events if isinstance(e, ToolResultAdded)}
    running = [e.tool for e in events if isinstance(e, ToolCalled) and e.call_id not in done]
    return f"running {', '.join(running)}" if running else "thinking"


class Assignee(BaseModel):
    role: Literal["agent", "customer", "approver", "insurer"]
    name: str | None = None  # the insurer's name; the UI names the customer and approver


_WITH_INSURER = ("submitted", "received", "approved")


def assignee(case: CaseFile, busy: bool, awaiting_approval: bool) -> Assignee:
    """Whose move it is, like a ticket assignee. The user plays both customer and approver."""
    if awaiting_approval:
        return Assignee(role="approver")
    if busy:
        return Assignee(role="agent")
    if case.insurer.stage in _WITH_INSURER:
        return Assignee(role="insurer", name=case.policy.insurer if case.policy else None)
    return Assignee(role="customer")


def ui_status(
    case: CaseFile, events: Sequence[CaseEvent], today: date, busy: bool, awaiting_approval: bool
) -> dict[str, Any]:
    """The status bar as the UI receives it over SSE."""
    return {
        **render_status(case, today).model_dump(mode="json"),
        "current_activity": current_activity(events, busy, awaiting_approval),
        "trace_view": trace_view(events).model_dump(),
        "assignee": assignee(case, busy, awaiting_approval).model_dump(),
    }


def approval_card(case: CaseFile, summary: str) -> dict[str, Any]:
    """The approval panel: the agent's summary, the policy as it stands, the change asked for."""
    return {
        "summary": summary,
        "policy": case.policy.model_dump() if case.policy else None,
        "change_type": case.change_request.type if case.change_request else None,
        "details": case.change_request.details if case.change_request else {},
        "slots": {name: s.value for name, s in case.slots.items()},
        "waivers": case.waivers,
    }


class ContextItem(BaseModel):
    kind: Literal["system", "user", "assistant", "tool", "skill", "upload", "status"]
    text: str
    in_prompt: bool  # False: it has left the prompt (old status bar, compressed or stubbed)
    note: str | None = None


def _message_item(m: BaseMessage) -> ContextItem:
    if isinstance(m, ToolMessage):
        return ContextItem(kind="tool", text=text_of(m.content), in_prompt=True, note=m.name)
    if isinstance(m, AIMessage):
        calls = [
            f"→ {c['name']}({json.dumps(c['args'], ensure_ascii=False)})" for c in m.tool_calls
        ]
        text = "\n".join(filter(None, [text_of(m.content), *calls]))
        return ContextItem(kind="assistant", text=text, in_prompt=True)
    mid = m.id or ""
    if isinstance(m, HumanMessage) and mid.startswith(UPLOAD_PREFIX):
        return ContextItem(kind="upload", text=text_of(m.content), in_prompt=True)
    if mid.startswith(SKILL_PREFIX):
        return ContextItem(kind="skill", text=text_of(m.content), in_prompt=True)
    return ContextItem(kind="user", text=text_of(m.content), in_prompt=True)


def context_log(
    messages: Sequence[BaseMessage], events: Sequence[CaseEvent], today: date
) -> list[ContextItem]:
    """Everything the model has been shown, in order.

    Each model call's status bar is rebuilt from the events before it (it is never stored);
    only the next call's bar is in the prompt. Compressed results and stubbed images show the
    original (out) followed by what replaced it (in).
    """
    originals = {e.call_id: e.content for e in events if isinstance(e, ToolResultAdded)}
    compressed = {cid for e in events if isinstance(e, ContextCompressed) for cid in e.call_ids}
    stubbed = {e.doc_id for e in events if isinstance(e, ImageStubbed)}
    filenames = {e.doc_id: e.filename for e in events if isinstance(e, DocumentUploaded)}
    bars: dict[int, list[str]] = {}
    for i, e in enumerate(events):
        if isinstance(e, ModelCalled):
            case = fold(events[:i])
            bars.setdefault(e.n_messages, []).append(to_text(render_status(case, today)))

    def old_bars(n: int) -> list[ContextItem]:
        return [ContextItem(kind="status", text=b, in_prompt=False) for b in bars.get(n, [])]

    items = [ContextItem(kind="system", text=SYSTEM_PROMPT, in_prompt=True, note="role + SOP")]
    for i, m in enumerate(messages):
        items += old_bars(i)
        item = _message_item(m)
        if isinstance(m, ToolMessage) and m.tool_call_id in compressed:
            original = originals.get(m.tool_call_id, "")
            items.append(ContextItem(kind="tool", text=original, in_prompt=False, note=m.name))
            item.note = f"{m.name}, compressed"
        doc_id = (m.id or "").removeprefix(UPLOAD_PREFIX)
        if item.kind == "upload" and doc_id in stubbed:
            image = f"[uploaded {doc_id}: {filenames.get(doc_id, '?')}] + image"
            items.append(ContextItem(kind="upload", text=image, in_prompt=False))
            item.note = "image stubbed"
        items.append(item)
    items += old_bars(len(messages))
    current = fold(events)
    items.append(
        ContextItem(
            kind="status",
            text=to_text(render_status(current, today)),
            in_prompt=True,
            note="next call",
        )
    )
    return items
