"""Terminal chat against the real models: `uv run python -m endorsement_agent`.

A smoke test. Needs `.env` with all four roles. A line
`/upload <path> ...` attaches documents to the next message.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from dotenv import load_dotenv

from endorsement_agent.config import Limits, fixed_today
from endorsement_agent.consistency import LLMChecker
from endorsement_agent.event_store import EventStore
from endorsement_agent.events import CaseCreated
from endorsement_agent.graph import Agent, build_graph
from endorsement_agent.history import LLMCompressor
from endorsement_agent.llm import chat_model
from endorsement_agent.mock_world.insurer import MockInsurer
from endorsement_agent.mock_world.policies import PolicyStore
from endorsement_agent.mock_world.rules import RulesMaster
from endorsement_agent.runtime import Runtime, Upload
from endorsement_agent.skills import SkillLibrary
from endorsement_agent.tracing import callbacks
from endorsement_agent.vision import LLMVision


async def main() -> None:
    load_dotenv()
    limits = Limits.from_env()
    case_id = f"case-{uuid.uuid4().hex[:8]}"
    store = EventStore()
    store.create(
        CaseCreated(
            case_id=case_id,
            ask_budget=limits.ask_budget,
            compress_threshold=limits.compress_threshold,
        )
    )
    rt = Runtime(
        case_id=case_id,
        store=store,
        policies=PolicyStore.load(),
        rules=RulesMaster.load(),
        insurer=MockInsurer(),
        skills=SkillLibrary(),
        vision=LLMVision(chat_model("extractor")),
        checker=LLMChecker(chat_model("judge")),
        fixed_today=fixed_today(),
    )
    graph = build_graph(rt, chat_model("agent"), LLMCompressor(chat_model("compressor")), limits)
    agent = Agent(rt, graph, callbacks())
    print(f"{case_id} — type a message; empty line to quit.")
    pending: list[Upload] = []
    while text := input("you> ").strip():
        if text.startswith("/upload "):
            for name in text.split()[1:]:
                path = Path(name)
                mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
                pending.append(rt.add_upload(path.name, mime, path.read_bytes()))
            continue
        result = await agent.send(text, pending)
        pending = []
        while result.approval is not None:
            print(f"[approval] {result.approval['summary']}")
            answer = input("approve? [y/n/c(hanges)] ").strip().lower()[:1]
            decision = {"y": "approved", "c": "changes_requested"}.get(answer, "rejected")
            reason = None if decision == "approved" else input("reason> ")
            result = await agent.resume({"decision": decision, "reason": reason})
        print(f"agent> {result.reply}")
    print(json.dumps([e.type for e in rt.events()]))


if __name__ == "__main__":
    asyncio.run(main())
