from __future__ import annotations

import yaml

from endorsement_agent import reference
from endorsement_agent.skills import SkillLibrary
from endorsement_agent.tools import TOOLS


def test_every_tool_is_documented_and_nothing_else() -> None:
    raw = yaml.safe_load(reference.TOOL_DOCS.read_text())
    assert set(raw["tools"]) == set(TOOLS)
    assert {d["group"] for d in raw["tools"].values()} <= {g["id"] for g in raw["groups"]}


def test_build_covers_all_tools_and_skills() -> None:
    skills = SkillLibrary()
    ref = reference.build(skills)
    assert [t["name"] for t in ref["tools"]] == list(TOOLS)
    assert [s["name"] for s in ref["skills"]] == skills.names
    slot = next(t for t in ref["tools"] if t["name"] == "record_slot")
    assert {a["name"]: a["required"] for a in slot["args"]}["supersede"] is False
    assert "change-of-owner" not in slot["skills"] and "nominee-update" in slot["skills"]
    coo = next(s for s in ref["skills"] if s["name"] == "change-of-owner")
    assert [r["name"] for r in coo["references"]] == ["transfer-form.md"]
