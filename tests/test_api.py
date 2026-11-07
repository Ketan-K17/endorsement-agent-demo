from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from endorsement_agent.api import CASE_TTL_S, MakeAgent, Session, create_app
from endorsement_agent.config import Limits, Quotas
from endorsement_agent.graph import Agent, build_graph
from endorsement_agent.quotas import SPENT_CASE, Meter
from endorsement_agent.skills import SkillLibrary
from tests.fakes import ScriptedModel, call, calls, runtime
from tests.test_graph import no_compress
from tests.test_tools import owner_transfer_ready

Client = tuple[httpx.AsyncClient, Callable[[str], Session]]


def scripted(script: list[AIMessage]) -> MakeAgent:
    def make(case_id: str, meter: Meter) -> Agent:
        rt = runtime(SkillLibrary(), case_id=case_id)
        model = ScriptedModel(script=script, callbacks=[meter])
        graph = build_graph(rt, model, no_compress, Limits(), stop=meter.stop)
        return Agent(rt, graph, callbacks=[])

    return make


async def client(script: list[AIMessage], **quotas: Any) -> Client:
    app = create_app(scripted(script), Quotas(**quotas))
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return http, lambda sid: app.state.sessions[sid]


async def new_session(http: httpx.AsyncClient) -> str:
    r = await http.post("/api/sessions")
    assert r.status_code == 201
    return str(r.json()["session_id"])


async def finish(s: Session) -> None:
    if s.task is not None:
        await s.task


async def until(stream: AsyncIterator[dict[str, str]], event: str) -> list[dict[str, Any]]:
    """Read the stream up to and including the next `event` message."""
    seen = []
    while True:
        m = await asyncio.wait_for(anext(stream), timeout=2)
        seen.append({"event": m["event"], "data": json.loads(m["data"]), "id": m.get("id")})
        if m["event"] == event:
            return seen


async def test_demo_lists_policies_and_fixture_cases() -> None:
    http, _ = await client([])
    body = (await http.get("/api/demo")).json()
    assert len(body["policies"]) == 15
    case_01 = next(c for c in body["cases"] if c["id"] == "case_01_owner_transfer_clean")
    assert "policy_copy.png" in case_01["docs"]
    assert (await http.get(f"/fixtures/{case_01['id']}/policy_copy.png")).status_code == 200


async def test_unknown_session_is_404() -> None:
    http, _ = await client([])
    assert (await http.post("/api/sessions/nope/messages", json={"text": "hi"})).status_code == 404


async def test_a_session_can_be_looked_up_by_id() -> None:
    http, _ = await client([])
    sid = await new_session(http)
    assert (await http.get(f"/api/sessions/{sid}")).json() == {"session_id": sid, "busy": False}
    assert (await http.get("/api/sessions/nope")).status_code == 404


async def test_an_earlier_case_replays_in_full_after_another_is_opened() -> None:
    http, session = await client([AIMessage(content="Hi.")])
    first = await new_session(http)
    await http.post(f"/api/sessions/{first}/messages", json={"text": "hi"})
    await finish(session(first))
    second = await new_session(http)
    await http.post(f"/api/sessions/{second}/messages", json={"text": "other case"})
    await finish(session(second))

    # a reload or a switch back connects from the start and gets the whole log
    backlog = await until(session(first).stream(0), "status")
    types = [m["data"].get("type") for m in backlog[:-1]]
    assert types == ["case.created", "message.user", "model.called", "message.assistant"]
    assert backlog[1]["data"]["text"] == "hi"
    assert backlog[-1]["data"]["current_activity"] == "idle"


async def test_a_message_streams_events_status_and_the_reply() -> None:
    http, session = await client([calls(call("get_case", "g1")), AIMessage(content="Hello.")])
    sid = await new_session(http)
    stream = session(sid).stream(0)
    backlog = await until(stream, "status")
    assert [m["event"] for m in backlog] == ["event", "status"]
    assert backlog[0]["data"]["type"] == "case.created" and backlog[0]["id"] == "1"

    png = base64.b64encode(b"\x89PNG fake").decode()
    files = [{"filename": "rc.png", "mime": "image/png", "data": png}]
    r = await http.post(f"/api/sessions/{sid}/messages", json={"text": "hi", "files": files})
    assert r.status_code == 202
    seen = await until(stream, "turn")
    types = [m["data"]["type"] for m in seen if m["event"] == "event"]
    assert types[:3] == ["document.uploaded", "message.user", "model.called"]
    assert "tool.result" in types and types[-1] == "message.assistant"
    statuses = [m["data"] for m in seen if m["event"] == "status"]
    assert statuses and statuses[0]["current_activity"] == "thinking"  # after the tool result
    assert seen[-1]["data"] == {"reply": "Hello.", "approval": None}
    [final] = await until(stream, "status")
    assert final["data"]["current_activity"] == "idle"
    await stream.aclose()
    assert session(sid)._queues == set()


async def test_a_reconnect_resumes_after_the_last_event_id() -> None:
    http, session = await client([AIMessage(content="Hi.")])
    sid = await new_session(http)
    await http.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    await finish(session(sid))
    backlog = await until(session(sid).stream(2), "status")
    assert [m["data"].get("type") for m in backlog[:-1]] == ["model.called", "message.assistant"]


async def test_approval_round_trip() -> None:
    http, session = await client(
        [
            calls(call("validate_case", "v1"), call("request_approval", "a1", summary="transfer")),
            AIMessage(content="Approved, submitting."),
        ]
    )
    sid = await new_session(http)
    await owner_transfer_ready(session(sid).rt)
    await http.post(f"/api/sessions/{sid}/messages", json={"text": "go ahead"})
    await finish(session(sid))
    card = session(sid).approval
    assert card is not None and card["summary"] == "transfer"
    assert card["policy"]["policy_no"] == "NWG-MOT-240117"
    assert card["slots"]["new_owner_name"] == "Meera Shetty"

    blocked = await http.post(f"/api/sessions/{sid}/messages", json={"text": "hello?"})
    assert blocked.status_code == 409
    # a client that connects now is shown the pending approval
    backlog = await until(session(sid).stream(0), "turn")
    assert backlog[-1]["data"]["approval"]["summary"] == "transfer"

    r = await http.post(f"/api/sessions/{sid}/approval", json={"decision": "approved"})
    assert r.status_code == 202
    await finish(session(sid))
    assert session(sid).approval is None
    assert session(sid).rt.case.approval.status == "approved"
    again = await http.post(f"/api/sessions/{sid}/approval", json={"decision": "approved"})
    assert again.status_code == 409


async def test_a_busy_session_refuses_a_second_message() -> None:
    http, session = await client([AIMessage(content="one")])
    sid = await new_session(http)
    await http.post(f"/api/sessions/{sid}/messages", json={"text": "a"})
    r = await http.post(f"/api/sessions/{sid}/messages", json={"text": "b"})
    assert r.status_code == 409
    await finish(session(sid))


async def test_a_failed_turn_reports_an_error_and_frees_the_session() -> None:
    http, session = await client([])  # the scripted model has nothing to say: it raises
    sid = await new_session(http)
    stream = session(sid).stream(0)
    await until(stream, "status")
    await http.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    seen = await until(stream, "agent_error")
    assert "error" in seen[-1]["data"]["message"]
    await finish(session(sid))
    assert not session(sid).busy


@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": "x", "files": [{"filename": "a.pdf", "mime": "application/pdf", "data": ""}]},
    ],
)
async def test_bad_messages_are_rejected(body: dict[str, Any]) -> None:
    http, _ = await client([])
    sid = await new_session(http)
    assert (await http.post(f"/api/sessions/{sid}/messages", json=body)).status_code == 422


async def test_context_lists_what_the_model_saw() -> None:
    http, session = await client([AIMessage(content="Hi.")])
    sid = await new_session(http)
    await http.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    await finish(session(sid))
    items = (await http.get(f"/api/sessions/{sid}/context")).json()
    assert [(i["kind"], i["in_prompt"]) for i in items] == [
        ("system", True),
        ("user", True),
        ("status", False),
        ("assistant", True),
        ("status", True),
    ]


def used(text: str, tokens: int) -> AIMessage:
    """A reply that reports `tokens` used."""
    usage = {"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens}
    return AIMessage(content=text, usage_metadata=usage)  # type: ignore[arg-type]


async def test_a_case_answers_only_to_the_browser_that_opened_it() -> None:
    http, _ = await client([])
    r = await http.post("/api/sessions")
    sid = r.json()["session_id"]
    assert "httponly" in r.headers["set-cookie"].lower()
    other = httpx.AsyncClient(transport=http._transport, base_url="http://test")
    for r in [
        await other.get(f"/api/sessions/{sid}"),
        await other.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}),
        await other.get(f"/api/sessions/{sid}/context"),
    ]:
        assert r.status_code == 404
    assert (await http.get(f"/api/sessions/{sid}")).status_code == 200
    # the same browser keeps its owner across cases
    owner = http.cookies["owner"]
    await new_session(http)
    assert http.cookies["owner"] == owner


async def test_an_invite_code_gates_opening_a_case() -> None:
    http, _ = await client([], invite_code="sesame")
    assert (await http.post("/api/sessions")).status_code == 403
    wrong = await http.post("/api/sessions", headers={"X-Invite-Code": "nope"})
    assert wrong.status_code == 403
    ok = await http.post("/api/sessions", headers={"X-Invite-Code": "sesame"})
    assert ok.status_code == 201


async def test_the_switch_off_closes_the_demo() -> None:
    http, _ = await client([], daily_budget_switch="off")
    r = await http.post("/api/sessions")
    assert r.status_code == 503 and "closed" in r.json()["detail"]


async def test_an_ip_is_limited_in_cases_it_starts_not_cases_it_opens() -> None:
    http, session = await client([AIMessage(content=c) for c in "abc"], ip_max_sessions_per_day=2)
    a, b, c = [await new_session(http) for _ in range(3)]  # opening is free: a bare / opens one
    hi = {"text": "hi"}
    for sid in (a, b):
        assert (await http.post(f"/api/sessions/{sid}/messages", json=hi)).status_code == 202
        await finish(session(sid))
    refused = await http.post(f"/api/sessions/{c}/messages", json=hi)
    assert refused.status_code == 429 and "2 cases" in refused.json()["detail"]
    # a later message in a started case is not a new case
    assert (await http.post(f"/api/sessions/{a}/messages", json=hi)).status_code == 202
    await finish(session(a))


async def test_a_case_out_of_tokens_refuses_more_messages() -> None:
    http, session = await client([used("Hi.", 120)], session_max_tokens=100)
    sid = await new_session(http)
    await http.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    await finish(session(sid))
    assert session(sid).meter.tokens == 120
    r = await http.post(f"/api/sessions/{sid}/messages", json={"text": "more"})
    assert r.status_code == 429 and r.json()["detail"] == SPENT_CASE


async def test_the_model_call_cap_ends_a_turn_on_a_fixed_reply() -> None:
    script = [calls(call("get_case", "g1")), AIMessage(content="never reached")]
    http, session = await client(script, session_max_model_calls=1)
    sid = await new_session(http)
    stream = session(sid).stream(0)
    await until(stream, "status")
    await http.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    seen = await until(stream, "turn")
    assert seen[-1]["data"]["reply"] == SPENT_CASE
    model_calls = [m for m in seen if m["data"].get("type") == "model.called"]
    assert len(model_calls) == 1  # the capped step made no model call
    await stream.aclose()
    await finish(session(sid))


async def test_the_daily_budget_counts_every_case() -> None:
    http, session = await client([used("a", 60), used("b", 60)], daily_max_tokens=100)
    first = await new_session(http)
    await http.post(f"/api/sessions/{first}/messages", json={"text": "hi"})
    await finish(session(first))
    second = await new_session(http)
    await http.post(f"/api/sessions/{second}/messages", json={"text": "hi"})
    await finish(session(second))
    r = await http.post("/api/sessions")
    assert r.status_code == 503 and "today" in r.json()["detail"]


async def test_idle_cases_are_dropped_and_live_cases_are_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("endorsement_agent.api.MAX_LIVE_CASES", 2)
    http, session = await client([])
    old, live = await new_session(http), await new_session(http)
    assert (await http.post("/api/sessions")).status_code == 503
    session(old).last_active -= CASE_TTL_S + 1
    await new_session(http)  # the idle one made room
    assert (await http.get(f"/api/sessions/{old}")).status_code == 404
    assert (await http.get(f"/api/sessions/{live}")).status_code == 200
