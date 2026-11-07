"""Role-based chat models on Azure OpenAI (ADR-0007). Swapping keys is an env-var change."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import AzureChatOpenAI

from endorsement_agent.config import Role, role_config


def chat_model(
    role: Role,
    callbacks: list[BaseCallbackHandler] | None = None,
    extra_body: dict[str, Any] | None = None,
) -> AzureChatOpenAI:
    """`callbacks` see every call on this model, e.g. a case's usage meter (ADR-0025).
    `extra_body` adds request fields, e.g. the agent's cache options (ADR-0026)."""
    c = role_config(role)
    return AzureChatOpenAI(
        callbacks=callbacks,
        extra_body=extra_body,
        azure_endpoint=c.endpoint,
        api_key=c.api_key,
        azure_deployment=c.deployment,
        api_version=c.api_version,
        timeout=90,
        max_retries=2,
        stream_usage=True,  # token counts for the trace view while streaming
    )
