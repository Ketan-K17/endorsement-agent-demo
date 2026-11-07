"""Reference docs for the Reference tab: every tool and skill, built from the live registries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from endorsement_agent.skills import SkillLibrary, _split
from endorsement_agent.tools import TOOLS

TOOL_DOCS = Path(__file__).parent / "tool_docs.yaml"


class ToolDoc(BaseModel):
    group: str
    summary: str
    when: str
    guardrails: str


def _type(p: dict[str, Any]) -> str:
    if "enum" in p:
        return " | ".join(map(str, p["enum"]))
    if p.get("type") == "array":
        return f"list of {p.get('items', {}).get('type', 'values')}"
    if "type" in p:
        return str(p["type"])
    kinds = [t.get("type", "?") for t in p.get("anyOf", []) if t.get("type") != "null"]
    return " | ".join(kinds)


def _args(model: type[BaseModel]) -> list[dict[str, Any]]:
    schema = model.model_json_schema()
    required = set(schema.get("required", []))
    return [
        {
            "name": name,
            "type": _type(p),
            "required": name in required,
            "description": p.get("description", ""),
        }
        for name, p in schema.get("properties", {}).items()
    ]


def build(skills: SkillLibrary) -> dict[str, Any]:
    raw = yaml.safe_load(TOOL_DOCS.read_text())
    docs = {name: ToolDoc.model_validate(d) for name, d in raw["tools"].items()}
    used_by: dict[str, list[str]] = {}
    for s in skills.catalog:
        for t in s.tools_hint:
            used_by.setdefault(t, []).append(s.name)
    tools: list[dict[str, Any]] = [
        {
            "name": t.name,
            "description": t.description,
            "args": _args(t.args),
            "skills": used_by.get(t.name, []),
            **docs[t.name].model_dump(),
        }
        for t in TOOLS.values()
    ]
    out_skills = []
    for s in skills.catalog:
        folder = skills.root / s.name
        body = _split((folder / "SKILL.md").read_text())[1]
        refs = sorted(p.name for p in (folder / "references").glob("*") if p.is_file())
        out_skills.append(
            {
                **s.model_dump(),
                "body": body,
                "references": [{"name": r, "text": skills.read(s.name, r)} for r in refs],
            }
        )
    return {"groups": raw["groups"], "tools": tools, "skills": out_skills}
