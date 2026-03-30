"""Enhanced agent factory that uses deepagents.create_deep_agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from deepagents.graph import BASE_AGENT_PROMPT

from deepagents_web.extensions.context_utils import find_project_root
from deepagents_web.extensions.settings import settings

if TYPE_CHECKING:
    from langgraph.pregel import Pregel


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
    """Create a deep agent with enhanced context management.

    Wraps ``deepagents.create_deep_agent`` with two additions:

    1. **CONTEXT.md auto-initialization** – creates a template when the file
       does not yet exist in the project's ``.deepagents/`` directory.
    2. **Multi-source memory loading** – feeds both AGENTS.md and CONTEXT.md
       into the agent so it can see accumulated project knowledge on every turn.

    Accepts ``enable_cua`` and ``cua_config`` for backward compatibility with
    callers that still pass these parameters, but silently ignores them.

    Returns ``(agent, None)`` where *agent* is a ``CompiledStateGraph``.
    The second element is ``None`` for backward compat with callers expecting
    a ``(agent, backend)`` tuple from the old ``create_cli_agent`` API.
    """
    tools = tools or []

    # ---- Ensure agent directory & AGENTS.md exist ----
    agent_dir = settings.ensure_agent_dir(assistant_id)
    agent_md = agent_dir / "AGENTS.md"
    if not agent_md.exists():
        agent_md.write_text(BASE_AGENT_PROMPT)

    # ---- Auto-initialize project CONTEXT.md ----
    _init_project_context()

    # ---- Build memory sources (AGENTS.md + CONTEXT.md) ----
    memory_sources: list[str] = [str(agent_md)]
    project_root = find_project_root()
    if project_root:
        context_md = project_root / ".deepagents" / "CONTEXT.md"
        if context_md.exists():
            memory_sources.append(str(context_md))
        project_agents_md = project_root / ".deepagents" / "AGENTS.md"
        if project_agents_md.exists():
            memory_sources.append(str(project_agents_md))

    # ---- Build skill sources ----
    skill_sources: list[str] = []
    user_skills_dir = settings.get_user_skills_dir(assistant_id)
    if user_skills_dir.exists():
        skill_sources.append(str(user_skills_dir))
    project_skills_dir = settings.get_project_skills_dir()
    if project_skills_dir and project_skills_dir.exists():
        skill_sources.append(str(project_skills_dir))

    # ---- Build backend ----
    if enable_shell:
        backend: Any = LocalShellBackend()
    else:
        from deepagents.backends import FilesystemBackend

        backend = FilesystemBackend(root_dir=str(Path.cwd()))

    # ---- Create agent ----
    agent = create_deep_agent(
        model=model,
        name=assistant_id,
        tools=tools,
        system_prompt=system_prompt,
        memory=memory_sources if enable_memory else None,
        skills=skill_sources if (enable_skills and skill_sources) else None,
        checkpointer=checkpointer,
        backend=backend,
    )

    return agent, None
