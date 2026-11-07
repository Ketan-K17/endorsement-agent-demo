"""Regression: once validation passes, the turn must reach `request_approval`, not stop.

Usage: uv run python evals/approval_after_pass.py [-k RUNS]

Needs the AGENT and COMPRESSOR roles in `.env`. From session case-d6399feb (case 05, name
typo): validation passed and the agent replied "I'm unable to initiate approval right now".
The cause was the per-turn tool-call cap, not the model: the turn had made 20 tool calls,
MAX_TOOL_CALLS_PER_TURN was 20, so the next call was bound with tool_choice="none".

The first five model calls of that session are replayed from the recording against the real
tools, with the recorded document readings, so every run reaches the same state. From there
the real agent model decides. A run passes if the turn pauses for approval; it fails if the
turn ends on a reply, and says when the cap had been reached. Prints pass@1 and pass^k.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda

from endorsement_agent.config import Limits
from endorsement_agent.event_store import EventStore
from endorsement_agent.events import CaseCreated, ExtractedField
from endorsement_agent.graph import Agent, build_graph, tool_calls_this_turn
from endorsement_agent.history import LLMCompressor
from endorsement_agent.llm import chat_model
from endorsement_agent.mock_world.insurer import MockInsurer
from endorsement_agent.mock_world.policies import PolicyStore
from endorsement_agent.mock_world.rules import RulesMaster
from endorsement_agent.runtime import Classification, Runtime, Upload
from endorsement_agent.skills import SkillLibrary
from endorsement_agent.tracing import callbacks

DOCS = Path(__file__).resolve().parent.parent / "fixtures" / "documents" / "case_05_name_typo"
TODAY = date(2026, 10, 15)  # FIXED_TODAY in the recorded session
MESSAGE = "My name is misspelt on policy CDM-PV-5529417. It should be Jignesh Patel."


def _call(tool: str, n: int, **args: object) -> dict[str, Any]:
    return {"name": tool, "args": args, "id": f"call_{n}", "type": "tool_call"}


def recorded_calls() -> list[AIMessage]:
    """The session's first five model calls, up to and including `validate_case`."""
    steps = [
        [
            _call(
                "record_slot",
                1,
                name="policy_no",
                value="CDM-PV-5529417",
                source="user_msg",
                confidence=1,
            ),
            _call(
                "record_slot",
                2,
                name="corrected_name",
                value="Jignesh Patel",
                source="user_msg",
                confidence=1,
            ),
            _call("lookup_policy", 3, policy_no="CDM-PV-5529417"),
            _call(
                "record_change_request",
                4,
                type="name-correction",
                details={"requested_name": "Jignesh Patel"},
            ),
            _call("load_skill", 5, name="name-correction"),
            _call("list_documents", 6),
        ],
        [
            _call("get_endorsement_rules", 7, type="name-correction", insurer="Cedar Mutual"),
            _call("classify_document", 8, doc_id="doc_1"),
            _call("classify_document", 9, doc_id="doc_2"),
        ],
        [
            _call("extract_fields", 10, doc_id="doc_1", fields=["name"]),
            _call("extract_fields", 11, doc_id="doc_2", fields=["owner_name", "reg_no"]),
            _call(
                "record_slot",
                12,
                name="correct_name",
                value="Jignesh Patel",
                source="user_msg",
                confidence=1,
            ),
            _call(
                "waive_requirement",
                13,
                name="name_change_proof",
                reason="Policy holder is Jignesh Pattel and requested/ID name is Jignesh "
                "Patel; this is a one-letter spelling correction, not a legal name change.",
            ),
        ],
        [
            _call(
                "record_slot",
                14,
                name="pan_name",
                value="JIGNESH PATEL",
                source="doc:doc_1",
                confidence=1,
            ),
            _call(
                "record_slot",
                15,
                name="rc_owner_name",
                value="JIGNESH PATEL",
                source="doc:doc_2",
                confidence=0.99,
            ),
            _call(
                "record_slot",
                16,
                name="rc_reg_no",
                value="GJ01RT8840",
                source="doc:doc_2",
                confidence=0.99,
            ),
            _call("cross_check", 17, a="policy.holder_name", b="doc_1.name"),
            _call("cross_check", 18, a="policy.holder_name", b="doc_2.owner_name"),
            _call("cross_check", 19, a="policy.reg_no", b="doc_2.reg_no"),
        ],
        [_call("validate_case", 20)],
    ]
    return [AIMessage(content="", tool_calls=calls) for calls in steps]


class RecordedVision:
    """The readings the extractor returned in the recorded session."""

    types = {"doc_1": "pan", "doc_2": "rc"}
    fields = {
        "doc_1": {"name": ExtractedField(value="JIGNESH PATEL", confidence=1.0)},
        "doc_2": {
            "owner_name": ExtractedField(value="JIGNESH PATEL", confidence=0.99),
            "reg_no": ExtractedField(value="GJ01RT8840", confidence=0.99),
        },
    }

    async def classify(self, upload: Upload, doc_types: list[str]) -> Classification:
        return Classification(doc_type=self.types[upload.doc_id], quality="ok")

    async def extract(
        self, upload: Upload, doc_type: str, fields: list[str]
    ) -> dict[str, ExtractedField]:
        return {k: v for k, v in self.fields[upload.doc_id].items() if k in fields}


class NoIssues:
    """The recorded `validate_case` LLM pass found nothing."""

    async def check(self, facts: str, previous: list[str]) -> list[str]:
        return []


class ReplayThenLive:
    """Answers from the recording first, then hands every later call to the live model."""

    def __init__(self, recorded: list[AIMessage], live: BaseChatModel) -> None:
        self.recorded = recorded
        self.live = live

    def bind_tools(
        self, tools: Sequence[Any], tool_choice: str | None = None
    ) -> Runnable[Any, BaseMessage]:
        live = self.live.bind_tools(tools, tool_choice=tool_choice)

        async def invoke(messages: list[BaseMessage]) -> BaseMessage:
            if self.recorded:
                return self.recorded.pop(0)
            return await live.ainvoke(messages)

        return RunnableLambda(invoke)


async def run_once(n: int) -> tuple[bool, str]:
    """One run: True if the turn paused for approval, with what the agent did instead if not."""
    limits = Limits.from_env()
    case_id = f"eval-approval-after-pass-{n}"
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
        vision=RecordedVision(),
        checker=NoIssues(),
        fixed_today=TODAY,
    )
    docs = ("pan.png", "rc.png")
    uploads = [rt.add_upload(d, "image/png", (DOCS / d).read_bytes()) for d in docs]
    model = ReplayThenLive(recorded_calls(), chat_model("agent"))
    compressor = LLMCompressor(chat_model("compressor"))
    graph = build_graph(rt, model, compressor, limits)  # duck-typed: only bind_tools is used
    agent = Agent(rt, graph, callbacks())
    result = await agent.send(MESSAGE, uploads)
    if result.approval is not None:
        return True, ""
    used = tool_calls_this_turn(agent.messages())
    capped = f" [tool-call cap reached: {used}/{limits.max_tool_calls_per_turn}]"
    return False, (result.reply or "") + (capped if used >= limits.max_tool_calls_per_turn else "")


async def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-k", type=int, default=5, help="runs (default 5)")
    k = parser.parse_args().k
    passed = 0
    for n in range(1, k + 1):
        ok, reply = await run_once(n)
        passed += ok
        print(f"run {n}: {'pass' if ok else 'FAIL'}" + ("" if ok else f" — replied: {reply!r}"))
    print(f"pass@1 {passed / k:.0%} · pass^{k} {'yes' if passed == k else 'no'}")
    return 0 if passed == k else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
