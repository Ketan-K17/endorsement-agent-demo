from __future__ import annotations

from datetime import date

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from endorsement_agent.config import Quotas
from endorsement_agent.quotas import SPENT_TODAY, Gate, Meter, tokens_used


def result(*totals: int) -> LLMResult:
    gens = [
        ChatGeneration(
            message=AIMessage(
                content="",
                usage_metadata={"input_tokens": t, "output_tokens": 0, "total_tokens": t},
            )
        )
        for t in totals
    ]
    return LLMResult(generations=[gens])


def test_tokens_used_sums_the_reply_usage_and_skips_missing() -> None:
    assert tokens_used(result(30, 12)) == 42
    assert tokens_used(LLMResult(generations=[[ChatGeneration(message=AIMessage(""))]])) == 0


def test_the_day_resets_the_budget_and_ip_counts() -> None:
    day = [date(2026, 11, 7)]
    gate = Gate(Quotas(daily_max_tokens=100, ip_max_sessions_per_day=1), lambda: day[0])
    meter = Meter(gate)
    meter.on_llm_end(result(100))
    assert gate.closed() == SPENT_TODAY
    assert gate.start("1.2.3.4") is None and gate.start("1.2.3.4") is not None
    day[0] = date(2026, 11, 8)
    assert gate.closed() is None
    assert gate.start("1.2.3.4") is None
    assert meter.tokens == 100  # the case's own count does not reset


def test_cache_reads_are_not_counted() -> None:
    usage = {
        "input_tokens": 5000,
        "output_tokens": 50,
        "total_tokens": 5050,
        "input_token_details": {"cache_read": 4000, "cache_creation": 900},
    }
    gen = ChatGeneration(message=AIMessage(content="", usage_metadata=usage))  # type: ignore[arg-type]
    assert tokens_used(LLMResult(generations=[[gen]])) == 1050
