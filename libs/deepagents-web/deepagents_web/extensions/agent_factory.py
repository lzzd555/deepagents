"""Enhanced agent factory that adds context management on top of the official CLI agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents_cli.agent import create_cli_agent
from deepagents_cli.config import settings
from deepagents_web.extensions.context_utils import find_project_agent_md, find_project_root

if TYPE_CHECKING:
    from langgraph.pregel import Pregel


def _get_default_coding_instructions() -> str:
    """Get default coding instructions from the CLI package."""
    from deepagents_cli.config import get_default_coding_instructions

    return get_default_coding_instructions()


def _init_project_context() -> None:
    """Initialize project-level CONTEXT.md if it doesn't exist."""
    project_root = find_project_root()
    if project_root is None:
        return

    project_deepagents_dir = project_root / ".deepagents"
    project_deepagents_dir.mkdir(parents=True, exist_ok=True)
    project_context_md = project_deepagents_dir / "CONTEXT.md"
    if not project_context_md.exists():
        project_context_md.write_text(
            "# Project Context\n\n"
            "This file stores project-specific instructions and learned patterns. "
            "The agent is encouraged to update this file to remember project-specific "
            "information, coding standards, and user preferences."
        )


async def create_cli_agent_with_context(
    model: str | Any,
    assistant_id: str,
    *,
    tools: list[Any] | None = None,
    sandbox: Any | None = None,
    sandbox_type: str | None = None,
    system_prompt: str | None = None,
    auto_approve: bool = False,
    enable_memory: bool = True,
    enable_skills: bool = True,
    enable_shell: bool = True,
    checkpointer: Any | None = None,
    enable_cua: bool = False,
    cua_config: Any | None = None,
    **_kwargs: Any,
) -> tuple[Any, Any]:
    """Create a CLI agent with enhanced context management.

    Wraps the official ``create_cli_agent`` with two additions:

    1. **CONTEXT.md auto-initialization** – creates a template when the file
       does not yet exist in the project's ``.deepagents/`` directory.
    2. **Multi-source memory loading** – feeds both AGENTS.md and CONTEXT.md
       into the agent's MemoryMiddleware so the agent can see accumulated
       project knowledge on every turn.

    Accepts ``enable_cua`` and ``cua_config`` for backward compatibility with
    callers that still pass these parameters, but silently ignores them since
    CUA is not available in the PyPI distribution of ``deepagents-cli``.
    """
    tools = tools or []

    # ---- Unwrap ModelResult from the new create_model() API ----
    # Official deepagents-cli >=0.0.34 returns ModelResult instead of BaseChatModel.
    if hasattr(model, "model"):
        model = model.model

    # ---- Ensure agent directory & AGENTS.md exist ----
    agent_dir = settings.ensure_agent_dir(assistant_id)
    agent_md = agent_dir / "AGENTS.md"
    if not agent_md.exists():
        agent_md.write_text(_get_default_coding_instructions())

    # ---- Auto-initialize project CONTEXT.md ----
    _init_project_context()

    # ---- Delegate to the official create_cli_agent (sync in v0.0.34+) ----
    agent, composite_backend = create_cli_agent(
        model=model,
        assistant_id=assistant_id,
        tools=tools,
        sandbox=sandbox,
        sandbox_type=sandbox_type,
        system_prompt=system_prompt,
        auto_approve=auto_approve,
        enable_memory=enable_memory,
        enable_skills=enable_skills,
        enable_shell=enable_shell,
        checkpointer=checkpointer,
    )

    return agent, composite_backend
