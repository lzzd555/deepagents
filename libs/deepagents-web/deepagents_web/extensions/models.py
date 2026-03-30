"""Model creation utilities, replacing deepagents_cli.config.create_model."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langchain.chat_models import init_chat_model

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def _default_model_spec() -> str:
    """Determine the default model spec from environment variables.

    Priority:
    1. ``DEEPAGENTS_MODEL`` – explicit override
    2. ``OPENAI_MODEL``     – prefixed with ``openai:`` so that
       ``init_chat_model`` routes through the OpenAI provider (which
       also honours ``OPENAI_BASE_URL`` for custom / compatible endpoints)
    3. ``claude-sonnet-4-6`` – fallback
    """
    explicit = os.environ.get("DEEPAGENTS_MODEL")
    if explicit:
        return explicit

    openai_model = os.environ.get("OPENAI_MODEL")
    if openai_model:
        if not openai_model.startswith("openai:"):
            return f"openai:{openai_model}"
        return openai_model

    return "claude-sonnet-4-6"


def create_model(model_spec: str | None = None) -> BaseChatModel:
    """Create a ``BaseChatModel`` from a model spec string.

    Uses ``langchain.chat_models.init_chat_model`` internally so that
    OpenAI-compatible proxies (``OPENAI_BASE_URL``) work out of the box.
    """
    spec = model_spec or _default_model_spec()
    return init_chat_model(spec)
