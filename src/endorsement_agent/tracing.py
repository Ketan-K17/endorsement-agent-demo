"""Langfuse tracing (ADR-0009). Optional: without keys the agent runs untraced."""

from __future__ import annotations

import os

from langchain_core.callbacks import BaseCallbackHandler


def callbacks() -> list[BaseCallbackHandler]:
    """A Langfuse handler when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set."""
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]
