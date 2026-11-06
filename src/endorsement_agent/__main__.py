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

from endorsement_agent.api import live_agent
from endorsement_agent.runtime import Upload


async def main() -> None:
    load_dotenv()
    case_id = f"case-{uuid.uuid4().hex[:8]}"
    agent = live_agent(case_id)
    rt = agent.rt
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
