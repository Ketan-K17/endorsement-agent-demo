"""Mock policy store (DESIGN §13). Lookup by policy no, reg no or phone; may match several."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, TypeAdapter

from endorsement_agent.events import PolicySnapshot

DATA = Path(__file__).parent / "data"


class Vehicle(BaseModel):
    make: str
    model: str
    variant: str
    fuel: str
    seating_capacity: int


class Period(BaseModel):
    start: date
    end: date


class Holder(BaseModel):
    name: str
    phone: str
    email: str
    address: str


class Nominee(BaseModel):
    name: str
    relation: str
    age: int


class Policy(BaseModel):
    policy_no: str
    insurer: str
    reg_no: str
    chassis_no: str
    engine_no: str
    vehicle: Vehicle
    period: Period
    holder: Holder
    nominee: Nominee | None = None
    hypothecated_to: str | None = None
    status: Literal["active", "lapsed"] = "active"

    def snapshot(self) -> PolicySnapshot:
        return PolicySnapshot(
            policy_no=self.policy_no,
            insurer=self.insurer,
            reg_no=self.reg_no,
            holder_name=self.holder.name,
            nominee_name=self.nominee.name if self.nominee else None,
            extra={
                "status": self.status,
                "hypothecated_to": self.hypothecated_to or "none",
                "vehicle": f"{self.vehicle.make} {self.vehicle.model} {self.vehicle.variant}",
            },
        )


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _phone(s: str) -> str:
    return re.sub(r"\D", "", s)[-10:]


class PolicyStore:
    def __init__(self, policies: list[Policy]) -> None:
        self.policies = policies

    @classmethod
    def load(cls, path: Path = DATA / "policies.yaml") -> PolicyStore:
        raw = yaml.safe_load(path.read_text())
        return cls(TypeAdapter(list[Policy]).validate_python(raw))

    def lookup(
        self, policy_no: str | None = None, reg_no: str | None = None, phone: str | None = None
    ) -> list[Policy]:
        """Exact match on any one key, ignoring case, spaces and punctuation. [] if not found."""
        if policy_no:
            return [p for p in self.policies if _norm(p.policy_no) == _norm(policy_no)]
        if reg_no:
            return [p for p in self.policies if _norm(p.reg_no) == _norm(reg_no)]
        if phone and len(_phone(phone)) == 10:
            return [p for p in self.policies if _phone(p.holder.phone) == _phone(phone)]
        if phone:
            return []
        raise ValueError("give one of policy_no, reg_no or phone")
