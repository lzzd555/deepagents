"""Session utilities, replacing deepagents_cli.sessions."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.checkpoint.base import BaseCheckpointSaver


class SessionState:
    """Minimal session state, replacing ``deepagents_cli.config.SessionState``."""

    def __init__(self, auto_approve: bool = False) -> None:
        self.auto_approve = auto_approve
        self.thread_id = str(uuid.uuid4())


@asynccontextmanager
async def get_checkpointer() -> AsyncGenerator[BaseCheckpointSaver, None]:
    """Yield an ``AsyncSqliteSaver`` context manager.

    Replaces ``deepagents_cli.sessions.get_checkpointer``.
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = Path.home() / ".deepagents" / "checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as cp:
        yield cp
