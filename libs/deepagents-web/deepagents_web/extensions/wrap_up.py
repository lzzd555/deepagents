"""Legacy Capture: wrap-up session to persist learned context into CONTEXT.md."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.pregel import Pregel

logger = logging.getLogger(__name__)


async def wrap_up_session(
    agent: Pregel,
    config: dict,
    assistant_id: str,
) -> None:
    """Perform a final invisible turn to capture learned context into CONTEXT.md.

    This implements the 'Legacy Capture' philosophy from ScienceClaw.
    """
    cwd = Path.cwd()
    context_path = cwd / ".deepagents" / "CONTEXT.md"

    wrap_up_input = {
        "messages": [
            {
                "role": "user",
                "content": (
                    f"[SYSTEM] CRITICAL: The session is closing. You MUST perform a final 'Knowledge Capture'.\n\n"
                    f"1. Review the entire conversation history.\n"
                    f"2. Identify any new project paths, coding standards, technical decisions, or user preferences.\n"
                    f"3. Use the `write_file` tool to update the file at `{context_path}` with a structured summary.\n\n"
                    f"Format the content as follows:\n"
                    f"# Project Context\n"
                    f"## Recent Learned Patterns\n"
                    f"- [List key learnings here]\n"
                    f"## Project Structure Notes\n"
                    f"- [List path/architecture discoveries]\n"
                    f"## User Preferences\n"
                    f"- [List persistent preferences]\n\n"
                    f"You MUST write the full content. Do not leave it empty. "
                    f"If no new knowledge was found, summarize the current task status instead. "
                    f"Execute the tool call NOW."
                ),
            }
        ]
    }

    # Execute and wait for completion
    try:
        from langgraph.types import Command

        async for chunk in agent.astream(
            wrap_up_input,
            config=config,
            stream_mode=["updates", "messages"],
        ):
            # If we hit an interrupt even with auto_approve (shouldn't happen, but for safety)
            if isinstance(chunk, tuple) and len(chunk) == 3:
                _ns, mode, data = chunk
                if mode == "updates" and "__interrupt__" in data:
                    # Force resume any interrupts during wrap-up
                    interrupts = data["__interrupt__"]
                    if interrupts:
                        decisions = {}
                        for interrupt in interrupts:
                            # Approve everything in wrap-up
                            action_reqs = interrupt.value.get("action_requests", [])
                            decisions[interrupt.id] = {
                                "decisions": [{"type": "approve"} for _ in action_reqs]
                            }
                        await agent.ainvoke(Command(resume=decisions), config=config)
    except Exception as e:
        logger.exception("Failed to wrap up session memory")
