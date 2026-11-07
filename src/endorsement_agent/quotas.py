"""Usage limits for the public demo (ADR-0025): who may start a case, and when one must stop.

Counts live in memory, so a restart resets the day. The day is the Asia/Kolkata calendar day,
never `FIXED_TODAY`.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from endorsement_agent.config import Quotas
from endorsement_agent.events import CaseEvent, ModelCalled
from endorsement_agent.runtime import TIMEZONE

CLOSED = "The demo is closed for now. Please come back later."
SPENT_TODAY = "The demo has used its budget for today. Please come back tomorrow."
SPENT_CASE = (
    "This case has reached its usage limit, so I can't take it any further. "
    "You can start a new case to try another."
)


def india_today() -> date:
    return datetime.now(TIMEZONE).date()


def tokens_used(response: LLMResult) -> int:
    """Tokens of one model call, less cache reads (ADR-0026), from the reply's usage."""
    total = 0
    for generation in (g for gs in response.generations for g in gs):
        if isinstance(generation, ChatGeneration) and isinstance(generation.message, AIMessage):
            if usage := generation.message.usage_metadata:
                cached = usage.get("input_token_details", {}).get("cache_read") or 0
                total += usage["total_tokens"] - cached
    return total


@dataclass
class Refusal:
    status: int
    detail: str


class Gate:
    """The day's counts across every case."""

    def __init__(self, quotas: Quotas, today: Callable[[], date] = india_today) -> None:
        self.quotas = quotas
        self._today = today
        self._day = today()
        self._tokens = 0
        self._started: dict[str, int] = {}  # cases per IP that have had a first message

    def _roll(self) -> None:
        if (day := self._today()) != self._day:
            self._day, self._tokens, self._started = day, 0, {}

    def spend(self, tokens: int) -> None:
        self._roll()
        self._tokens += tokens

    def closed(self) -> str | None:
        """Why no case may run now, if none may."""
        if not self.quotas.daily_budget_switch:
            return CLOSED
        self._roll()
        if self._tokens >= self.quotas.daily_max_tokens:
            return SPENT_TODAY
        return None

    def refuse_open(self, invite: str | None) -> Refusal | None:
        """Why a new case may not be opened, if it may not."""
        if (code := self.quotas.invite_code) is not None and not hmac.compare_digest(
            (invite or "").encode(), code.get_secret_value().encode()
        ):
            return Refusal(403, "invite code required")
        if reason := self.closed():
            return Refusal(503, reason)
        return None

    def start(self, ip: str) -> Refusal | None:
        """Count a case's first message against its IP, or refuse it."""
        self._roll()
        limit = self.quotas.ip_max_sessions_per_day
        if self._started.get(ip, 0) >= limit:
            return Refusal(429, f"This address has used its {limit} cases for today.")
        self._started[ip] = self._started.get(ip, 0) + 1
        return None


class Meter(BaseCallbackHandler):
    """One case's usage: tokens on every role it runs, each also counted toward the day."""

    run_inline = True  # count on the event loop, not in a worker thread

    def __init__(self, gate: Gate) -> None:
        self.gate = gate
        self.tokens = 0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:  # noqa: ANN401
        n = tokens_used(response)
        self.tokens += n
        self.gate.spend(n)

    def stop(self, events: Sequence[CaseEvent]) -> str | None:
        """Why the case must stop before its next agent call, if it must."""
        if reason := self.gate.closed():
            return reason
        quotas = self.gate.quotas
        calls = sum(isinstance(e, ModelCalled) for e in events)
        if calls >= quotas.session_max_model_calls or self.tokens >= quotas.session_max_tokens:
            return SPENT_CASE
        return None
