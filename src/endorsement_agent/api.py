"""FastAPI backend: sessions, messages, approval, and one SSE stream per session (DESIGN §14).

`uv run uvicorn endorsement_agent.api:create_app --factory --port 7860`.
A session is one case, in memory. The stream sends every case event (`event`, id = seq),
agent text deltas (`token`), the UI status bar after each tool result and each turn
(`status`), turn ends (`turn`) and `agent_error` (not `error`, which EventSource fires itself
when the connection drops).
Usage limits and case owners: ADR-0025. A case answers only to the `owner` cookie that
opened it; anyone else gets 404.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Base64Bytes, BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from endorsement_agent import reference
from endorsement_agent.config import Limits, Quotas, fixed_today
from endorsement_agent.consistency import LLMChecker
from endorsement_agent.event_store import EventStore
from endorsement_agent.events import CaseCreated, CaseEvent, ToolResultAdded
from endorsement_agent.graph import Agent, TurnResult, build_graph
from endorsement_agent.history import LLMCompressor
from endorsement_agent.llm import chat_model
from endorsement_agent.mock_world.insurer import MockInsurer
from endorsement_agent.mock_world.policies import PolicyStore
from endorsement_agent.mock_world.rules import RulesMaster
from endorsement_agent.quotas import Gate, Meter
from endorsement_agent.runtime import Runtime
from endorsement_agent.skills import SkillLibrary
from endorsement_agent.tools import ApprovalDecision
from endorsement_agent.tracing import callbacks
from endorsement_agent.views import approval_card, context_log, ui_status
from endorsement_agent.vision import LLMVision

logger = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
FIXTURES = Path(__file__).parents[2] / "fixtures" / "documents"
MAX_FILE_BYTES = 8 * 1024 * 1024
OWNER_COOKIE = "owner"
MAX_LIVE_CASES = 40  # Render free has 512 MB; a case holds its uploads
CASE_TTL_S = 2 * 3600  # idle cases are dropped after this

# Starter messages for the fixture cases in the "Demo policies" picker (DESIGN §13). They carry
# no documents; the UI puts the case's files in a dock for the user to add when they choose.
DEMO_CASES = {
    "case_01_owner_transfer_clean": (
        "Change of owner",
        "Hi, I bought a used Maruti Swift, KA05MZ4182, and want its insurance moved to my "
        "name.",
    ),
    "case_03_nominee_update": (
        "Nominee update",
        "Hello, please change the nominee on my policy HLA/MC/88104577 to my daughter, "
        "Divya Narayanan.",
    ),
    "case_05_name_typo": (
        "Name correction",
        "My name is misspelt on policy CDM-PV-5529417. It should be Jignesh Patel.",
    ),
}


def live_agent(case_id: str, meter: Meter | None = None) -> Agent:
    """A case on the real models (all four roles from env). `meter` limits its usage."""
    limits = Limits.from_env()
    cbs: list[Any] | None = [meter] if meter is not None else None
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
        vision=LLMVision(chat_model("extractor", cbs)),
        checker=LLMChecker(chat_model("judge", cbs)),
        fixed_today=fixed_today(),
    )
    # Only the GPT-5.6 agent takes explicit cache breakpoints; older models reject them.
    cache = {"prompt_cache_options": {"mode": "explicit"}, "prompt_cache_key": case_id}
    graph = build_graph(
        rt,
        chat_model("agent", cbs, extra_body=cache),
        LLMCompressor(chat_model("compressor", cbs)),
        limits,
        stop=meter.stop if meter is not None else None,
        cache_breakpoints=True,
    )
    return Agent(rt, graph, callbacks())


SSE = dict[str, str]
Run = Callable[[Callable[[str], None]], Awaitable[TurnResult]]
MakeAgent = Callable[[str, Meter], Agent]


class Session:
    """One case: its agent, owner and usage, the turn in flight, and the open SSE streams."""

    def __init__(self, agent: Agent, meter: Meter, owner: str) -> None:
        self.agent = agent
        self.rt = agent.rt
        self.meter = meter
        self.owner = owner
        self.started = False  # has had a first message, counted against its IP
        self.last_active = time.monotonic()
        self.task: asyncio.Task[None] | None = None
        self.approval: dict[str, Any] | None = None  # the approval card while one is pending
        self._queues: set[asyncio.Queue[SSE]] = set()
        self.rt.store.subscribe(self.rt.case_id, self._on_event)

    @property
    def busy(self) -> bool:
        return self.task is not None

    def expired(self, now: float) -> bool:
        """Idle past the TTL: no turn running, no stream open."""
        return not self.busy and not self._queues and now - self.last_active > CASE_TTL_S

    def status(self) -> dict[str, Any]:
        rt = self.rt
        return ui_status(rt.case, rt.events(), rt.today(), self.busy, self.approval is not None)

    def _publish(self, message: SSE) -> None:
        for q in self._queues:
            q.put_nowait(message)

    def _on_event(self, event: CaseEvent) -> None:
        self._publish(_event_message(event))
        if isinstance(event, ToolResultAdded):
            self._publish(_message("status", self.status()))

    def start(self, run: Run) -> None:
        """Run a turn in the background; its output reaches the client over SSE."""
        self.approval = None
        self.last_active = time.monotonic()
        self.task = asyncio.create_task(self._turn(run))

    async def _turn(self, run: Run) -> None:
        try:
            result = await run(lambda delta: self._publish(_message("token", {"text": delta})))
        except Exception:
            logger.exception("turn failed in %s", self.rt.case_id)
            self._publish(
                _message("agent_error", {"message": "The agent hit an error. Try again."})
            )
        else:
            if result.approval is not None:
                self.approval = approval_card(self.rt.case, result.approval["summary"])
            self._publish(_message("turn", {"reply": result.reply, "approval": self.approval}))
        finally:
            self.task = None
            self._publish(_message("status", self.status()))

    async def stream(self, after: int) -> AsyncIterator[SSE]:
        """Events after `after` (a reconnect resumes there), then the live stream."""
        queue: asyncio.Queue[SSE] = asyncio.Queue()
        self._queues.add(queue)
        # Snapshot right after subscribing, with no await between: nothing is lost or repeated.
        backlog = [_event_message(e) for e in self.rt.store.events(self.rt.case_id, after)]
        backlog.append(_message("status", self.status()))
        if self.approval is not None:
            backlog.append(_message("turn", {"reply": None, "approval": self.approval}))
        try:
            for message in backlog:
                yield message
            while True:
                yield await queue.get()
        finally:
            self._queues.discard(queue)
            self.last_active = time.monotonic()


def _message(event: str, data: object) -> SSE:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


def _event_message(event: CaseEvent) -> SSE:
    return {**_message("event", event.model_dump(mode="json")), "id": str(event.seq)}


class FileIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    mime: Literal["image/png", "image/jpeg"]
    data: Base64Bytes


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    files: list[FileIn] = Field(default_factory=list, max_length=12)


def client_ip(request: Request, header: str | None) -> str:
    """The visitor's address: `header` when set and present (ADR-0027), else the peer.
    Never `X-Forwarded-For`, whose first entry a visitor can forge on Render."""
    if header and (value := request.headers.get(header)):
        return value.strip()
    return request.client.host if request.client else "unknown"


def create_app(make_agent: MakeAgent | None = None, quotas: Quotas | None = None) -> FastAPI:
    if make_agent is None:
        load_dotenv()
        make_agent = live_agent
    new_agent = make_agent
    gate = Gate(quotas if quotas is not None else Quotas.from_env())
    sessions: dict[str, Session] = {}
    app = FastAPI(title="Endorsement agent")
    app.state.sessions = sessions
    app.state.gate = gate

    def session(request: Request, session_id: str) -> Session:
        s = sessions.get(session_id)
        owner = request.cookies.get(OWNER_COOKIE, "")
        if s is None or not hmac.compare_digest(s.owner.encode(), owner.encode()):
            raise HTTPException(404, "unknown session")
        return s

    def idle(s: Session) -> None:
        if s.busy:
            raise HTTPException(409, "the agent is still working on the last message")

    @app.get("/api/demo")
    def demo() -> dict[str, Any]:
        policies = [
            {
                "policy_no": p.policy_no,
                "insurer": p.insurer,
                "reg_no": p.reg_no,
                "holder": p.holder.name,
                "vehicle": f"{p.vehicle.make} {p.vehicle.model}",
            }
            for p in PolicyStore.load().policies
        ]
        cases = [
            {
                "id": case,
                "title": title,
                "starter": starter,
                "docs": sorted(f.name for f in (FIXTURES / case).glob("*.png")),
            }
            for case, (title, starter) in DEMO_CASES.items()
            if (FIXTURES / case).is_dir()
        ]
        return {"policies": policies, "cases": cases}

    @app.get("/api/reference")
    def reference_docs() -> dict[str, Any]:
        return reference.build(SkillLibrary())

    @app.post("/api/sessions", status_code=201)
    def create_session(
        request: Request, response: Response, x_invite_code: str | None = Header(None)
    ) -> dict[str, str]:
        if refusal := gate.refuse_open(x_invite_code):
            raise HTTPException(refusal.status, refusal.detail)
        now = time.monotonic()
        for sid in [sid for sid, s in sessions.items() if s.expired(now)]:
            del sessions[sid]
        if len(sessions) >= MAX_LIVE_CASES:
            raise HTTPException(503, "The demo is full right now. Please try again in a while.")
        owner = request.cookies.get(OWNER_COOKIE) or secrets.token_urlsafe(16)
        response.set_cookie(
            OWNER_COOKIE,
            owner,
            max_age=7 * 86400,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        case_id = f"case-{uuid.uuid4().hex[:8]}"
        meter = Meter(gate)
        sessions[case_id] = Session(new_agent(case_id, meter), meter, owner)
        return {"session_id": case_id}

    # Lets a reload or a switch back check a remembered case is still in memory (ADR-0022).
    @app.get("/api/sessions/{session_id}")
    def lookup(request: Request, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "busy": session(request, session_id).busy}

    @app.get("/api/sessions/{session_id}/stream")
    async def stream(
        request: Request,
        session_id: str,
        after: int = 0,
        last_event_id: str | None = Header(None),
    ) -> EventSourceResponse:
        s = session(request, session_id)
        if last_event_id and last_event_id.isdigit():
            after = max(after, int(last_event_id))
        return EventSourceResponse(s.stream(after), ping=15)

    # Async handlers: a turn is a task on the server's event loop, as are the SSE streams.
    @app.post("/api/sessions/{session_id}/messages", status_code=202)
    async def send(request: Request, session_id: str, body: MessageIn) -> dict[str, bool]:
        s = session(request, session_id)
        idle(s)
        if s.approval is not None:
            raise HTTPException(409, "approve, reject or request changes first")
        if any(len(f.data) > MAX_FILE_BYTES for f in body.files):
            raise HTTPException(413, f"each file must be under {MAX_FILE_BYTES // 2**20} MB")
        if reason := s.meter.stop(s.rt.events()):
            raise HTTPException(429, reason)
        if not s.started:
            if refusal := gate.start(client_ip(request, gate.quotas.client_ip_header)):
                raise HTTPException(refusal.status, refusal.detail)
            s.started = True
        uploads = [s.rt.add_upload(f.filename, f.mime, f.data) for f in body.files]
        s.start(lambda on_token: s.agent.send(body.text, uploads, on_token))
        return {"accepted": True}

    @app.post("/api/sessions/{session_id}/approval", status_code=202)
    async def decide(request: Request, session_id: str, body: ApprovalDecision) -> dict[str, bool]:
        s = session(request, session_id)
        idle(s)
        if s.approval is None:
            raise HTTPException(409, "nothing is waiting for approval")
        decision = body.model_dump()
        s.start(lambda on_token: s.agent.resume(decision, on_token))
        return {"accepted": True}

    @app.get("/api/sessions/{session_id}/context")
    def context(request: Request, session_id: str) -> list[dict[str, Any]]:
        s = session(request, session_id)
        items = context_log(s.agent.messages(), s.rt.events(), s.rt.today())
        return [i.model_dump() for i in items]

    if FIXTURES.is_dir():
        app.mount("/fixtures", StaticFiles(directory=FIXTURES), name="fixtures")
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
