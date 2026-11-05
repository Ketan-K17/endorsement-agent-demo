"""Run the real extractor over the fixture documents and compare with each `expected.json`.

Usage: uv run python tools/extract_fixtures.py [--out DIR] [case ...]

Needs the EXTRACTOR role in `.env`. Prints one line per field that differs; with --out, also
saves the raw output per case. `expected.json` is written by hand from what the documents
show, never from this output, so a misreading cannot become ground truth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from endorsement_agent.llm import chat_model
from endorsement_agent.mock_world.rules import RulesMaster
from endorsement_agent.runtime import Upload, VisionError
from endorsement_agent.validation import norm
from endorsement_agent.vision import LLMVision

ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "documents"

_RC = ["reg_no", "owner_name", "chassis_no", "engine_no", "hypothecated_to"]
_POLICY = [
    "policy_no",
    "reg_no",
    "holder_name",
    "chassis_no",
    "engine_no",
    "hypothecated_to",
    "nominee_name",
    "nominee_relation",
    "nominee_age",
]
FIELDS: dict[str, list[str]] = {
    "policy_copy": _POLICY,
    "rc": _RC,
    "aadhaar": ["name", "dob", "aadhaar_no", "address"],
    "pan": ["name", "dob", "pan_no"],
    "transfer_form": ["reg_no", "seller_name", "buyer_name", "transfer_date"],
}


async def read(vision: LLMVision, path: Path, doc_types: list[str]) -> dict[str, object]:
    upload = Upload(doc_id=path.stem, filename=path.name, mime="image/png", data=path.read_bytes())
    try:
        c = await vision.classify(upload, doc_types)
        fields = FIELDS.get(c.doc_type, [])
        got = await vision.extract(upload, c.doc_type, fields) if fields else {}
    except VisionError as e:
        return {"error": str(e)}
    return {
        "doc_type": c.doc_type,
        "quality": c.quality,
        "note": c.note,
        "fields": {k: v.model_dump() for k, v in got.items()},
    }


def diffs(name: str, got: dict[str, object], want: dict[str, object]) -> list[str]:
    out = [
        f"{name}: {key} is {got.get(key)!r}, expected {want[key]!r}"
        for key in ("doc_type", "quality")
        if key in want and got.get(key) != want[key]
    ]
    fields = got.get("fields")
    read_fields = fields if isinstance(fields, dict) else {}
    expected = want.get("fields")
    for field, value in (expected if isinstance(expected, dict) else {}).items():
        field_read = read_fields.get(field) or {}
        actual = field_read.get("value")
        if norm(actual or "") != norm(value or ""):
            out.append(
                f"{name}: {field} is {actual!r} "
                f"({field_read.get('confidence')}), expected {value!r}"
            )
    return out


async def run_case(vision: LLMVision, case: Path, doc_types: list[str], out: Path | None) -> int:
    paths = sorted(case.glob("*.png"))
    results = await asyncio.gather(*(read(vision, p, doc_types) for p in paths))
    got = {p.name: r for p, r in zip(paths, results, strict=True)}
    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{case.name}.json").write_text(json.dumps(got, indent=2) + "\n")
    expected_path = case / "expected.json"
    want = json.loads(expected_path.read_text()) if expected_path.exists() else {}
    found = [line for name, w in want.items() for line in diffs(name, got[name], w)]
    print(f"{case.name}: {len(paths)} files, {len(found)} differences")
    for line in found:
        print(f"  {line}")
    return len(found)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    load_dotenv()
    vision = LLMVision(chat_model("extractor"))
    doc_types = RulesMaster.load().doc_types
    cases = [ROOT / c for c in args.cases] or [d for d in sorted(ROOT.iterdir()) if d.is_dir()]
    total = 0
    for case in cases:
        if any(case.glob("*.png")):
            total += await run_case(vision, case, doc_types, args.out)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
