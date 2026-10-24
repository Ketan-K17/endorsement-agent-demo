"""Skill library: catalog from `SKILL.md` frontmatter, sandboxed reference reads (DESIGN §5)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

SKILLS_DIR = Path(__file__).parents[2] / "skills"


class SkillMeta(BaseModel):
    name: str
    description: str  # one "use when…" line, shown in the load_skill catalog
    tools_hint: list[str] = Field(default_factory=list)


def _split(text: str) -> tuple[dict[str, object], str]:
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front), body.strip()


class SkillLibrary:
    def __init__(self, root: Path = SKILLS_DIR) -> None:
        self.root = root.resolve()
        self.catalog: list[SkillMeta] = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            meta = SkillMeta.model_validate(_split(path.read_text())[0])
            if meta.name != path.parent.name:
                raise ValueError(f"{path}: name {meta.name!r} does not match its folder")
            self.catalog.append(meta)

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.catalog]

    def load(self, name: str) -> str:
        if name not in self.names:
            raise KeyError(f"unknown skill {name!r}")
        return (self.root / name / "SKILL.md").read_text()

    def read(self, skill: str, path: str) -> str:
        """Read a file under `<skill>/references/`; anything outside it is refused."""
        if skill not in self.names:
            raise KeyError(f"unknown skill {skill!r}")
        base = self.root / skill / "references"
        target = (base / path).resolve()
        if not target.is_relative_to(base):
            raise PermissionError(f"{path!r} is outside {skill}/references")
        if not target.is_file():
            raise FileNotFoundError(f"{skill}/references/{path} not found")
        return target.read_text()
