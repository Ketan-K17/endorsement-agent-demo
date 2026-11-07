"""Mock rules master: required docs and slots, fees and TAT per (type, insurer)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from endorsement_agent.events import DocRequirement, Requirements, SlotRequirement

DATA = Path(__file__).parent / "data"


class RuleRow(BaseModel):
    type: str
    insurer: str
    item: str
    mode: Literal["upload", "text"]
    condition: str | None = None
    note: str | None = None


class Terms(BaseModel):
    type: str
    insurer: str
    fee_inr: int
    tat_days: int
    handover_if: list[str] = Field(default_factory=list)


class EndorsementRules(BaseModel):
    """What `get_endorsement_rules` returns for one (type, insurer)."""

    type: str
    insurer: str
    fee_inr: int
    tat_days: int
    handover_if: list[str]
    rows: list[RuleRow]
    doc_parts: dict[str, list[str]] = Field(default_factory=dict)  # only types in `rows`

    def requirements(self) -> Requirements:
        return Requirements(
            docs=[
                DocRequirement(
                    name=r.item, condition=r.condition, parts=self.doc_parts.get(r.item, [])
                )
                for r in self.rows
                if r.mode == "upload"
            ],
            slots=[
                SlotRequirement(name=r.item, condition=r.condition)
                for r in self.rows
                if r.mode == "text"
            ],
        )


class RulesMaster(BaseModel):
    doc_types: list[str]
    doc_parts: dict[str, list[str]] = Field(default_factory=dict)
    terms: list[Terms]
    rows: list[RuleRow]

    @model_validator(mode="after")
    def _consistent(self) -> RulesMaster:
        keys = {(t.type, t.insurer) for t in self.terms}
        if unknown := set(self.doc_parts) - set(self.doc_types):
            raise ValueError(f"parts for unknown doc types: {sorted(unknown)}")
        seen: set[tuple[str, str, str]] = set()
        for r in self.rows:
            if (r.type, r.insurer) not in keys:
                raise ValueError(f"row without terms: {r.type} / {r.insurer}")
            if r.mode == "upload" and r.item not in self.doc_types:
                raise ValueError(f"unknown doc type: {r.item}")
            if (r.type, r.insurer, r.item) in seen:
                raise ValueError(f"duplicate row: {r.type} / {r.insurer} / {r.item}")
            seen.add((r.type, r.insurer, r.item))
        return self

    @classmethod
    def load(cls, path: Path = DATA / "rules.yaml") -> RulesMaster:
        return cls.model_validate(yaml.safe_load(path.read_text()))

    @property
    def types(self) -> list[str]:
        return sorted({t.type for t in self.terms})

    def get(self, type: str, insurer: str) -> EndorsementRules:
        """Exact match only: a short or reworded type is an error, never a silent miss."""
        terms = next((t for t in self.terms if (t.type, t.insurer) == (type, insurer)), None)
        if terms is None:
            raise KeyError(f"no rules for type={type!r} insurer={insurer!r}")
        rows = [r for r in self.rows if (r.type, r.insurer) == (type, insurer)]
        return EndorsementRules(
            type=type,
            insurer=insurer,
            fee_inr=terms.fee_inr,
            tat_days=terms.tat_days,
            handover_if=terms.handover_if,
            rows=rows,
            doc_parts={r.item: self.doc_parts[r.item] for r in rows if r.item in self.doc_parts},
        )
