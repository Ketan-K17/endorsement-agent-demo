"""Role-based chat models on Azure OpenAI (ADR-0007). Swapping keys is an env-var change."""

from __future__ import annotations

from langchain_openai import AzureChatOpenAI

from endorsement_agent.config import Role, role_config


def chat_model(role: Role) -> AzureChatOpenAI:
    c = role_config(role)
    return AzureChatOpenAI(
        azure_endpoint=c.endpoint,
        api_key=c.api_key,
        azure_deployment=c.deployment,
        api_version=c.api_version,
        timeout=90,
        max_retries=2,
    )
