"""The two sanctioned history transforms: image stubbing and tool-result compression (§6).

Both are deterministic in what they select, replace messages in place (same id), and leave
the originals in the event log. Neither touches user text or assistant messages.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from endorsement_agent.case_file import CaseFile
from endorsement_agent.events import ContextCompressed, compressible
from endorsement_agent.runtime import Upload

UPLOAD_PREFIX = "upload-"
SKILL_PREFIX = "skill-"  # skill text attached as a user message (ADR-0015)

Compressor = Callable[[str, dict[str, Any], str], Awaitable[str]]
"""(tool name, call args, raw result) -> compressed body."""


def upload_message(upload: Upload) -> HumanMessage:
    """One message per upload, id `upload-<doc_id>`, so stubbing can find its image."""
    data = base64.b64encode(upload.data).decode()
    return HumanMessage(
        id=f"{UPLOAD_PREFIX}{upload.doc_id}",
        content=[
            {"type": "text", "text": f"[uploaded {upload.doc_id}: {upload.filename}]"},
            {"type": "image_url", "image_url": {"url": f"data:{upload.mime};base64,{data}"}},
        ],
    )


def _has_image(m: BaseMessage) -> bool:
    return isinstance(m.content, list) and any(
        isinstance(p, dict) and p.get("type") == "image_url" for p in m.content
    )


def stub_images(messages: list[BaseMessage], case: CaseFile) -> list[HumanMessage]:
    """Replacements for upload messages whose doc has been classified and extracted."""
    done = {d.id for d in case.documents if d.type is not None and d.extraction is not None}
    out = []
    for m in messages:
        doc_id = (m.id or "").removeprefix(UPLOAD_PREFIX)
        if isinstance(m, HumanMessage) and m.id != doc_id and doc_id in done and _has_image(m):
            text = f"[image {doc_id} — see extraction above]"
            out.append(HumanMessage(id=m.id, content=text))
    return out


def tokens(text: str) -> int:
    """Rough estimate (4 chars a token). Only feeds the compression chip and meter."""
    return len(text) // 4


def _call_args(messages: list[BaseMessage]) -> dict[str, dict[str, Any]]:
    return {
        c["id"]: c["args"]
        for m in messages
        if isinstance(m, AIMessage)
        for c in m.tool_calls
        if c["id"]
    }


async def compress(
    messages: list[BaseMessage],
    case: CaseFile,
    already: set[str],
    compressor: Compressor,
) -> tuple[list[ToolMessage], ContextCompressed] | None:
    """Compress all uncompressed tool results but the latest, once the threshold is reached.

    `already` holds call ids compressed earlier; they are never counted or touched again.
    `ask_user` acks and results under `COMPRESS_MIN_CHARS` are left alone and not counted.
    """
    if case.context.uncompressed_tool_results < case.context.threshold:
        return None
    pending = [
        m
        for m in messages
        if isinstance(m, ToolMessage)
        and compressible(m.name or "", str(m.content))
        and m.tool_call_id not in already
    ]
    targets = pending[:-1]
    if not targets:
        return None
    args = _call_args(messages)
    bodies = await asyncio.gather(
        *(compressor(m.name or "", args.get(m.tool_call_id, {}), str(m.content)) for m in targets)
    )
    stubs = {
        m.tool_call_id: f"[compressed #{m.tool_call_id} {m.name}"
        f"({json.dumps(args.get(m.tool_call_id, {}), ensure_ascii=False)}): {body.strip()}]"
        for m, body in zip(targets, bodies, strict=True)
    }
    replaced = [
        ToolMessage(
            id=m.id, tool_call_id=m.tool_call_id, name=m.name, content=stubs[m.tool_call_id]
        )
        for m in targets
    ]
    event = ContextCompressed(
        call_ids=[m.tool_call_id for m in targets],
        tokens_before=sum(tokens(str(m.content)) for m in targets),
        tokens_after=sum(tokens(s) for s in stubs.values()),
        stubs=stubs,
    )
    return replaced, event


_COMPRESS_RULES = """\
Rewrite one tool result as a single compact line.
Keep every identifier, value, number, date, confidence, decision, status and error exactly.
Drop wording, boilerplate, field labels that repeat, and JSON punctuation.
Never add, infer or round anything. Output the line only."""

_TOOL_HINTS = {
    "lookup_policy": "Keep policy no, insurer, reg no, holder, nominee, period, status, financier.",
    "get_endorsement_rules": "Keep each item with its mode and condition, fee, TAT, handover_if.",
    "extract_fields": "Keep doc id, type, status, and every field as name=value (conf).",
    "classify_document": "Keep type, quality and note.",
    "validate_case": "Keep outcome, every issue and every diff line.",
}


class LLMCompressor:
    """Near-lossless compressor on the compressor role, with a hint per tool (ADR-0004)."""

    def __init__(self, model: BaseChatModel) -> None:
        self.model = model

    async def __call__(self, tool: str, args: dict[str, Any], content: str) -> str:
        hint = _TOOL_HINTS.get(tool, "")
        reply = await self.model.ainvoke(
            [
                SystemMessage(f"{_COMPRESS_RULES}\n{hint}".strip()),
                HumanMessage(f"tool: {tool}\nargs: {json.dumps(args)}\nresult:\n{content}"),
            ]
        )
        return str(reply.content)
