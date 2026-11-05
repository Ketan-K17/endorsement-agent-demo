"""Test doubles: a scripted chat model, a fake vision reader, a runtime factory."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import PrivateAttr

from endorsement_agent.event_store import EventStore
from endorsement_agent.events import CaseCreated, ExtractedField
from endorsement_agent.mock_world.insurer import MockInsurer
from endorsement_agent.mock_world.policies import PolicyStore
from endorsement_agent.mock_world.rules import RulesMaster
from endorsement_agent.runtime import Classification, Runtime, Upload, VisionError
from endorsement_agent.skills import SkillLibrary


def call(tool: str, call_id: str, **args: Any) -> dict[str, Any]:
    return {"name": tool, "args": args, "id": call_id, "type": "tool_call"}


def calls(*tool_calls: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=list(tool_calls))


class ScriptedModel(BaseChatModel):
    """Replies from a fixed script and records every prompt and bind_tools kwargs."""

    script: list[AIMessage]
    _prompts: list[list[BaseMessage]] = PrivateAttr(default_factory=list)
    _binds: list[dict[str, Any]] = PrivateAttr(default_factory=list)
    _kwargs: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    @property
    def prompts(self) -> list[list[BaseMessage]]:
        return self._prompts

    @property
    def call_kwargs(self) -> list[dict[str, Any]]:
        return self._kwargs

    @property
    def binds(self) -> list[dict[str, Any]]:
        return self._binds

    def bind_tools(  # type: ignore[override]
        self, tools: Sequence[Any], **kwargs: Any
    ) -> Runnable[Any, BaseMessage]:
        self._binds.append({"tools": tools, **kwargs})
        return self.bind(tool_choice_marker=kwargs.get("tool_choice"))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._prompts.append(list(messages))
        self._kwargs.append(kwargs)
        reply = self.script.pop(0)
        return ChatResult(generations=[ChatGeneration(message=reply)])


class FakeVision:
    """Classification and fields per doc id, set by the test."""

    def __init__(self) -> None:
        self.types: dict[str, Classification] = {}
        self.fields: dict[str, dict[str, ExtractedField]] = {}

    async def classify(self, upload: Upload, doc_types: list[str]) -> Classification:
        return self.types[upload.doc_id]

    async def extract(
        self, upload: Upload, doc_type: str, fields: list[str]
    ) -> dict[str, ExtractedField]:
        if upload.doc_id not in self.fields:
            raise VisionError("nothing legible")
        return {k: v for k, v in self.fields[upload.doc_id].items() if k in fields}


class FakeChecker:
    """Returns `issues` and records what it was given."""

    def __init__(self, issues: list[str] | None = None) -> None:
        self.issues = issues or []
        self.calls: list[tuple[str, list[str]]] = []

    async def check(self, facts: str, previous: list[str]) -> list[str]:
        self.calls.append((facts, previous))
        return self.issues


def runtime(skills: SkillLibrary, case_id: str = "case-1", ask_budget: int = 3) -> Runtime:
    store = EventStore()
    store.create(CaseCreated(case_id=case_id, ask_budget=ask_budget))
    return Runtime(
        case_id=case_id,
        store=store,
        policies=PolicyStore.load(),
        rules=RulesMaster.load(),
        insurer=MockInsurer(),
        skills=skills,
        vision=FakeVision(),
        fixed_today=date(2026, 10, 25),
    )
