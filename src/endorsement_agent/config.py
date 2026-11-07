"""Settings from the environment. Names are listed in `.env.example`; values never logged."""

from __future__ import annotations

import os
from datetime import date
from typing import Literal

from pydantic import BaseModel, SecretStr

Role = Literal["agent", "extractor", "compressor", "judge"]


class RoleConfig(BaseModel):
    endpoint: str
    api_key: SecretStr
    deployment: str
    api_version: str


def role_config(role: Role) -> RoleConfig:
    """Read `<ROLE>_ENDPOINT`, `_API_KEY`, `_DEPLOYMENT`, `_API_VERSION` (ADR-0007)."""
    prefix = role.upper()
    names = {f: f"{prefix}_{f.upper()}" for f in RoleConfig.model_fields}
    missing = [n for n in names.values() if not os.environ.get(n)]
    if missing:
        raise RuntimeError(f"missing env vars: {', '.join(missing)}")
    return RoleConfig.model_validate({f: os.environ[n] for f, n in names.items()})


def fixed_today() -> date | None:
    """`FIXED_TODAY` (YYYY-MM-DD) pins the date so fixture dates never go stale (ADR-0016)."""
    value = os.environ.get("FIXED_TODAY")
    return date.fromisoformat(value) if value else None


class Limits(BaseModel):
    compress_threshold: int = 5
    ask_budget: int = 3
    max_tool_calls_per_turn: int = 40

    @classmethod
    def from_env(cls) -> Limits:
        return cls.model_validate(
            {f: os.environ[f.upper()] for f in cls.model_fields if os.environ.get(f.upper())}
        )
