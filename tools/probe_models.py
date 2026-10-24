"""List Azure OpenAI deployments and probe each for chat, tools, vision and JSON schema.

Usage:
    AZURE_ENDPOINT=https://<resource>.openai.azure.com AZURE_API_KEY=... \\
        python tools/probe_models.py [deployment ...]

With no deployment arguments it probes every deployment the endpoint lists.
Prints deployment names, pass/fail and latency only; never prints the key.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

API_VERSION = os.environ.get("AZURE_API_VERSION", "2025-04-01-preview")
LIST_API_VERSION = "2023-03-15-preview"


def _png(width: int = 64, height: int = 64) -> str:
    """A valid solid-colour PNG, large enough for vision endpoints to accept."""
    raw = b"".join(b"\x00" + bytes([200, 30, 30]) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode()


def _call(
    endpoint: str, key: str, path: str, body: dict | None = None
) -> tuple[int, object, float]:
    request = urllib.request.Request(
        endpoint.rstrip("/") + path,
        data=json.dumps(body).encode() if body else None,
        headers={"api-key": key, "Content-Type": "application/json"},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, json.loads(response.read()), time.time() - started
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:200].replace("\n", " "), time.time() - started
    except (urllib.error.URLError, TimeoutError) as error:
        return 0, repr(error)[:200], time.time() - started


def _tests() -> dict[str, dict]:
    tool = {
        "type": "function",
        "function": {
            "name": "get_x",
            "description": "get x",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    }
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "o",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": False,
            },
        },
    }
    image = {"url": "data:image/png;base64," + _png()}
    return {
        "chat": {"messages": [{"role": "user", "content": "Say ok"}]},
        "tools": {
            "messages": [{"role": "user", "content": "Call get_x with id 7"}],
            "tools": [tool],
            "tool_choice": "required",
        },
        "vision": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in 3 words"},
                        {"type": "image_url", "image_url": image},
                    ],
                }
            ]
        },
        "json_schema": {
            "messages": [{"role": "user", "content": "Give a=hello"}],
            "response_format": schema,
        },
    }


def main() -> int:
    endpoint, key = os.environ.get("AZURE_ENDPOINT"), os.environ.get("AZURE_API_KEY")
    if not endpoint or not key:
        print("Set AZURE_ENDPOINT and AZURE_API_KEY.", file=sys.stderr)
        return 2

    deployments = sys.argv[1:]
    if not deployments:
        path = f"/openai/deployments?api-version={LIST_API_VERSION}"
        status, body, _ = _call(endpoint, key, path)
        if status != 200 or not isinstance(body, dict):
            print(f"Could not list deployments (HTTP {status}); pass names explicitly.")
            return 1
        deployments = [item["id"] for item in body.get("data", [])]
        print("deployments:", ", ".join(deployments))

    tests = _tests()
    for deployment in deployments:
        cells = []
        for name, body in tests.items():
            status, detail, elapsed = _call(
                endpoint,
                key,
                f"/openai/deployments/{deployment}/chat/completions?api-version={API_VERSION}",
                {**body, "max_completion_tokens": 400},
            )
            cells.append(f"{name}={'OK' if status == 200 else status}({elapsed:.1f}s)")
            if status != 200:
                cells[-1] += f" {str(detail)[:80]}"
        print(f"{deployment} | " + " ".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
