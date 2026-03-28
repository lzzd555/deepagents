"""Agent service for creating and streaming agent responses."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from deepagents_cli.config import SessionState, create_model
from deepagents_web.extensions.agent_factory import create_cli_agent_with_context as create_cli_agent
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

from deepagents_web.models.chat import InterruptRequest, InterruptResponse, WebSocketMessage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain.agents.middleware.human_in_the_loop import HITLResponse
    from langgraph.pregel import Pregel

logger = logging.getLogger(__name__)

# Constants for stream chunk validation
_STREAM_CHUNK_SIZE = 3
_MESSAGE_TUPLE_SIZE = 2


class AgentSession:
    """Manages a single agent session."""

    def __init__(
        self,
        session_id: str,
        session_state: SessionState,
        assistant_id: str,
    ) -> None:
        """Initialize the agent session."""
        self.session_id = session_id
        self.session_state = session_state
        self.config = {
            "configurable": {
                "thread_id": session_state.thread_id,
                # Keep a stable checkpoint namespace across per-turn agent
                # re-instantiation so LangGraph can recover the same history.
                "checkpoint_ns": f"web:{assistant_id}",
            }
        }
        self.pending_interrupts: dict[str, dict[str, Any]] = {}
        self.cancelled = False

    def cancel(self) -> None:
        """Cancel the current operation."""
        self.cancelled = True

    def reset_cancel(self) -> None:
        """Reset the cancel flag."""
        self.cancelled = False


class AgentService:
    """Service for managing agent sessions and streaming responses."""

    def __init__(
        self,
        agent_name: str = "agent",
        *,
        auto_approve: bool = False,
        enable_cua: bool = True,
        cua_model: str | None = None,
        cua_provider: str | None = None,
        cua_os: str | None = None,
        cua_trajectory_dir: str | None = None,
    ) -> None:
        """Initialize the agent service."""
        self.agent_name = agent_name
        self.auto_approve = auto_approve
        self.enable_cua = enable_cua
        self.cua_model = cua_model
        self.cua_provider = cua_provider
        self.cua_os = cua_os
        self.cua_trajectory_dir = cua_trajectory_dir
        self.sessions: dict[str, AgentSession] = {}

    async def create_session(self) -> str:
        """Create a new agent session."""
        session_id = str(uuid.uuid4())
        session_state = SessionState(auto_approve=self.auto_approve)
        self.sessions[session_id] = AgentSession(
            session_id=session_id,
            session_state=session_state,
            assistant_id=self.agent_name,
        )
        return session_id

    def get_session(self, session_id: str) -> AgentSession | None:
        """Get an existing session."""
        return self.sessions.get(session_id)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session after performing a wrap-up."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            
            # Perform final legacy capture before deletion
            try:
                # We need to recreate the agent one last time for the summary
                from deepagents_web.extensions.wrap_up import wrap_up_session

                # Manual instantiation inside delete_session
                from deepagents_web.extensions.agent_factory import create_cli_agent_with_context as create_cli_agent
                from deepagents_cli.config import create_model
                from deepagents_cli.sessions import get_checkpointer

                model = create_model()

                async with get_checkpointer() as checkpointer:
                    agent, _backend = await create_cli_agent(
                        model=model,
                        assistant_id=self.agent_name,
                        auto_approve=True, # Force True for final wrap-up
                        enable_shell=True,
                        enable_cua=self.enable_cua,
                        checkpointer=checkpointer,
                    )
                    await wrap_up_session(
                        agent=agent,
                        config=session.config,
                        assistant_id=self.agent_name,
                    )
            except Exception:
                logger.exception(f"Failed to wrap up session {session_id}")
            
            del self.sessions[session_id]
            return True
        return False

    def list_sessions(self) -> list[str]:
        """List all session IDs."""
        return list(self.sessions.keys())

    async def stream_response(
        self,
        session: AgentSession,
        user_input: str,
    ) -> AsyncGenerator[WebSocketMessage, None]:
        """Stream agent responses as WebSocket messages."""
        stream_input: dict[str, Any] | Command = {
            "messages": [{"role": "user", "content": user_input}]
        }

        async for msg in self._stream_agent(session, stream_input):
            yield msg

    async def resume_with_decision(
        self,
        session: AgentSession,
        response: InterruptResponse,
    ) -> AsyncGenerator[WebSocketMessage, None]:
        """Resume agent with HITL decision."""
        hitl_response: dict[str, HITLResponse] = {
            response.interrupt_id: {
                "decisions": [{"type": response.decision, "message": response.message}]
            }
        }
        stream_input = Command(resume=hitl_response)

        async for msg in self._stream_agent(session, stream_input):
            yield msg

    async def _stream_agent(
        self,
        session: AgentSession,
        stream_input: dict[str, Any] | Command,
    ) -> AsyncGenerator[WebSocketMessage, None]:
        """Internal method to stream agent responses."""
        tool_call_buffers: dict[str | int, dict[str, Any]] = {}
        session.reset_cancel()

        try:
            # Recreate agent instance for a request (Instant Instantiation)
            model = create_model()

            # We need the checkpointer to maintain conversation history
            # IT MUST STAY OPEN while agent.astream is running
            from deepagents_cli.sessions import get_checkpointer
            async with get_checkpointer() as checkpointer:
                agent, _backend = await create_cli_agent(
                    model=model,
                    assistant_id=self.agent_name,
                    auto_approve=session.session_state.auto_approve,
                    enable_shell=True,
                    enable_cua=self.enable_cua,
                    checkpointer=checkpointer,
                )

                async for chunk in agent.astream(
                    stream_input,
                    stream_mode=["messages", "updates"],
                    subgraphs=True,
                    config=session.config,
                ):
                    # Check if cancelled
                    if session.cancelled:
                        yield WebSocketMessage(type="text", data="\n\n[Stopped by user]")
                        break

                    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_SIZE:
                        continue

                    _namespace, stream_mode, data = chunk

                    if stream_mode == "updates":
                        async for msg in self._handle_updates(session, data):
                            yield msg

                    elif stream_mode == "messages":
                        async for msg in self._handle_messages(data, tool_call_buffers):
                            yield msg

        except Exception as e:
            logger.exception("Stream error")
            yield WebSocketMessage(type="error", data=f"Stream error: {e}")

    async def _handle_updates(
        self,
        session: AgentSession,
        data: Any,
    ) -> AsyncGenerator[WebSocketMessage, None]:
        """Handle updates stream for interrupts and todos."""
        if not isinstance(data, dict):
            return

        seen_interrupt_ids: set[str] = set()
        for interrupt in self._iter_interrupts(data):
            try:
                interrupt_id = getattr(interrupt, "id", None)
                if interrupt_id and interrupt_id in seen_interrupt_ids:
                    continue
                request_data = interrupt.value
                action_requests = request_data.get("action_requests", [])
                if not action_requests:
                    continue
                action = action_requests[0]
                interrupt_req = InterruptRequest(
                    interrupt_id=interrupt_id or "unknown",
                    tool_name=action.get("name", "unknown"),
                    description=action.get("description", ""),
                    args=action.get("args", {}),
                )
                if interrupt_id:
                    seen_interrupt_ids.add(interrupt_id)
                    session.pending_interrupts[interrupt_id] = request_data
                yield WebSocketMessage(type="interrupt", data=interrupt_req.model_dump())
            except (ValidationError, KeyError, AttributeError):
                continue

        todos = self._find_todos(data)
        if todos is not None:
            yield WebSocketMessage(type="todo", data=todos)

    def _iter_interrupts(self, data: Any) -> Iterable[Any]:
        if isinstance(data, dict):
            interrupts = data.get("__interrupt__")
            # Support both list and tuple types for interrupts
            if isinstance(interrupts, (list, tuple)):
                for interrupt in interrupts:
                    yield interrupt
            for value in data.values():
                yield from self._iter_interrupts(value)
        elif isinstance(data, (list, tuple)):
            for item in data:
                yield from self._iter_interrupts(item)

    def _find_todos(self, data: Any) -> list[dict[str, Any]] | None:
        if isinstance(data, dict):
            todos = data.get("todos")
            if isinstance(todos, list):
                return todos
            for value in data.values():
                found = self._find_todos(value)
                if found is not None:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = self._find_todos(item)
                if found is not None:
                    return found
        return None

    async def _handle_messages(
        self,
        data: Any,
        tool_call_buffers: dict[str | int, dict[str, Any]],
    ) -> AsyncGenerator[WebSocketMessage, None]:
        """Handle messages stream for text and tool calls."""
        if not isinstance(data, tuple) or len(data) != _MESSAGE_TUPLE_SIZE:
            return

        message, _metadata = data

        if isinstance(message, ToolMessage):
            tool_name = getattr(message, "name", "")
            tool_id = getattr(message, "tool_call_id", None)
            tool_status = getattr(message, "status", "success")
            tool_content = _format_tool_message_content(message.content)
            yield WebSocketMessage(
                type="tool_result",
                data={
                    "id": tool_id,
                    "name": tool_name,
                    "result": tool_content,
                    "status": tool_status,
                },
            )
            return

        if not hasattr(message, "content_blocks"):
            return

        for block in message.content_blocks:
            block_type = block.get("type")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    yield WebSocketMessage(type="text", data=text)

            elif block_type in ("tool_call_chunk", "tool_call"):
                tool_msg = self._process_tool_call(block, tool_call_buffers)
                if tool_msg:
                    yield tool_msg

    def _process_tool_call(
        self,
        block: dict[str, Any],
        buffers: dict[str | int, dict[str, Any]],
    ) -> WebSocketMessage | None:
        """Process tool call chunks and return message when complete."""
        chunk_name = block.get("name")
        chunk_args = block.get("args")
        chunk_id = block.get("id")
        chunk_index = block.get("index")

        buffer_key: str | int = self._get_buffer_key(chunk_index, chunk_id, len(buffers))

        buffer = buffers.setdefault(
            buffer_key,
            {"name": None, "id": None, "args": None, "args_parts": []},
        )

        if chunk_name:
            buffer["name"] = chunk_name
        if chunk_id:
            buffer["id"] = chunk_id

        self._update_buffer_args(buffer, chunk_args)

        buffer_name = buffer.get("name")
        if buffer_name is None:
            return None

        parsed_args = self._parse_buffer_args(buffer)
        if parsed_args is None:
            return None

        buffers.pop(buffer_key, None)
        return WebSocketMessage(
            type="tool_call",
            data={"name": buffer_name, "args": parsed_args, "id": buffer.get("id")},
        )

    def _get_buffer_key(
        self,
        chunk_index: int | None,
        chunk_id: str | None,
        buffer_count: int,
    ) -> str | int:
        """Get the buffer key for a tool call chunk."""
        if chunk_index is not None:
            return chunk_index
        if chunk_id is not None:
            return chunk_id
        return f"unknown-{buffer_count}"

    def _update_buffer_args(
        self,
        buffer: dict[str, Any],
        chunk_args: dict[str, Any] | str | None,
    ) -> None:
        """Update buffer with chunk args."""
        if isinstance(chunk_args, dict):
            buffer["args"] = chunk_args
            buffer["args_parts"] = []
        elif isinstance(chunk_args, str) and chunk_args:
            parts: list[str] = buffer.setdefault("args_parts", [])
            if not parts or chunk_args != parts[-1]:
                parts.append(chunk_args)
            buffer["args"] = "".join(parts)

    def _parse_buffer_args(self, buffer: dict[str, Any]) -> dict[str, Any] | None:
        """Parse buffer args to dict."""
        parsed_args = buffer.get("args")
        if isinstance(parsed_args, str):
            if not parsed_args:
                return None
            try:
                return json.loads(parsed_args)
            except json.JSONDecodeError:
                return None
        if parsed_args is None:
            return None
        return parsed_args


def _format_tool_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            else:
                try:
                    parts.append(json.dumps(item, ensure_ascii=False))
                except (TypeError, ValueError):
                    parts.append(str(item))
        return "\n".join(parts)
    return str(content)
