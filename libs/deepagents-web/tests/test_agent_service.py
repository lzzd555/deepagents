"""Tests for agent session persistence config."""

from __future__ import annotations

from contextlib import asynccontextmanager

from deepagents_web.services import agent_service as agent_service_module
from deepagents_web.services.agent_service import AgentService


async def test_create_session_uses_stable_checkpoint_namespace():
    """Sessions should keep a stable namespace across per-turn agent rebuilds."""
    service = AgentService(agent_name="agent")

    session_id = await service.create_session()
    session = service.get_session(session_id)

    assert session is not None
    assert session.config == {
        "configurable": {
            "thread_id": session.session_state.thread_id,
            "checkpoint_ns": "web:agent",
        }
    }


async def test_stream_response_reuses_same_session_config_across_turns(monkeypatch):
    """Per-turn agent recreation should still target the same checkpoint context."""

    class FakeMessage:
        def __init__(self, text: str) -> None:
            self.content_blocks = [{"type": "text", "text": text}]

    class FakeAgent:
        def __init__(self, turn_number: int) -> None:
            self.turn_number = turn_number

        async def astream(self, stream_input, *, stream_mode, subgraphs, config):
            seen_calls.append(
                {
                    "turn": self.turn_number,
                    "stream_input": stream_input,
                    "stream_mode": stream_mode,
                    "subgraphs": subgraphs,
                    "config": config,
                }
            )
            yield ("root", "messages", (FakeMessage(f"turn-{self.turn_number}"), {}))

    seen_calls: list[dict] = []
    created_turns = 0

    async def fake_create_cli_agent(**kwargs):
        nonlocal created_turns
        created_turns += 1
        return FakeAgent(created_turns), None

    @asynccontextmanager
    async def fake_get_checkpointer():
        yield object()

    monkeypatch.setattr(agent_service_module, "create_model", lambda: object())
    monkeypatch.setattr(agent_service_module, "create_cli_agent", fake_create_cli_agent)
    monkeypatch.setattr("deepagents_web.extensions.sessions.get_checkpointer", fake_get_checkpointer)

    service = AgentService(agent_name="agent", enable_cua=False)
    session_id = await service.create_session()
    session = service.get_session(session_id)

    assert session is not None

    first_turn = [msg async for msg in service.stream_response(session, "hello")]
    second_turn = [msg async for msg in service.stream_response(session, "remember me")]

    assert [msg.data for msg in first_turn] == ["turn-1"]
    assert [msg.data for msg in second_turn] == ["turn-2"]
    assert len(seen_calls) == 2
    assert seen_calls[0]["config"] == seen_calls[1]["config"] == session.config
    assert seen_calls[0]["config"]["configurable"]["thread_id"] == session.session_state.thread_id
    assert seen_calls[0]["config"]["configurable"]["checkpoint_ns"] == "web:agent"
    assert seen_calls[0]["stream_input"] == {"messages": [{"role": "user", "content": "hello"}]}
    assert seen_calls[1]["stream_input"] == {"messages": [{"role": "user", "content": "remember me"}]}


async def test_stream_response_can_resume_history_with_recreated_agents(monkeypatch):
    """A recreated agent should be able to read prior turn state from persistence."""

    class FakeMessage:
        def __init__(self, text: str) -> None:
            self.content_blocks = [{"type": "text", "text": text}]

    class FakeCheckpointer:
        def __init__(self) -> None:
            self.history: dict[tuple[str, str], list[str]] = {}

    class FakeAgent:
        def __init__(self, checkpointer: FakeCheckpointer) -> None:
            self.checkpointer = checkpointer

        async def astream(self, stream_input, *, stream_mode, subgraphs, config):
            cfg = config["configurable"]
            key = (cfg["thread_id"], cfg["checkpoint_ns"])
            prior_messages = list(self.checkpointer.history.get(key, []))
            current_message = stream_input["messages"][0]["content"]
            self.checkpointer.history[key] = [*prior_messages, current_message]
            yield ("root", "messages", (FakeMessage(f"prior={len(prior_messages)} current={current_message}"), {}))

    fake_checkpointer = FakeCheckpointer()
    created_agents: list[FakeAgent] = []

    async def fake_create_cli_agent(**kwargs):
        agent = FakeAgent(kwargs["checkpointer"])
        created_agents.append(agent)
        return agent, None

    @asynccontextmanager
    async def fake_get_checkpointer():
        yield fake_checkpointer

    monkeypatch.setattr(agent_service_module, "create_model", lambda: object())
    monkeypatch.setattr(agent_service_module, "create_cli_agent", fake_create_cli_agent)
    monkeypatch.setattr("deepagents_web.extensions.sessions.get_checkpointer", fake_get_checkpointer)

    service = AgentService(agent_name="agent", enable_cua=False)
    session_id = await service.create_session()
    session = service.get_session(session_id)

    assert session is not None

    first_turn = [msg async for msg in service.stream_response(session, "hello")]
    second_turn = [msg async for msg in service.stream_response(session, "remember me")]

    assert len(created_agents) == 2
    assert created_agents[0] is not created_agents[1]
    assert created_agents[0].checkpointer is fake_checkpointer
    assert created_agents[1].checkpointer is fake_checkpointer
    assert [msg.data for msg in first_turn] == ["prior=0 current=hello"]
    assert [msg.data for msg in second_turn] == ["prior=1 current=remember me"]
    assert fake_checkpointer.history == {
        (
            session.session_state.thread_id,
            "web:agent",
        ): ["hello", "remember me"]
    }
