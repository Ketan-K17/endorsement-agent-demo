"""Settings from the environment. Names are listed in `.env.example`; values never logged."""

from __future__ import annotations

import os
from datetime import date
from typing import Literal, Self

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


class _FromEnv(BaseModel):
    @classmethod
    def from_env(cls) -> Self:
        """Each field from the env var of the same name in upper case; unset keeps the default."""
        return cls.model_validate(
            {f: os.environ[f.upper()] for f in cls.model_fields if os.environ.get(f.upper())}
        )


class Limits(_FromEnv):
    compress_threshold: int = 5
    ask_budget: int = 3
    max_tool_calls_per_turn: int = 40


class Quotas(_FromEnv):
    """Usage limits for the public demo (ADR-0025)."""

    session_max_model_calls: int = 60  # agent calls
    session_max_tokens: int = 100_000  # all four roles, less cache reads
    ip_max_sessions_per_day: int = 3
    daily_max_tokens: int = 3_000_000
    daily_budget_switch: bool = True  # off closes the demo
    invite_code: SecretStr | None = None
