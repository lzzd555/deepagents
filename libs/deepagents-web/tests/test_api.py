"""Tests for deepagents-web."""

import pytest
from fastapi.testclient import TestClient

from deepagents_web.main import app
from deepagents_web.api import sessions as sessions_api


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


def test_health_endpoint(client):
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_redirects(client):
    """Test that root redirects to static index."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307


def test_list_skills_endpoint(client):
    """Test the list skills endpoint."""
    response = client.get("/api/skills")
    assert response.status_code == 200
    data = response.json()
    assert "skills" in data
    assert isinstance(data["skills"], list)


def test_list_sessions_endpoint(client):
    """Test the list sessions endpoint."""
    response = client.get("/api/sessions")
    assert response.status_code == 200
    data = response.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


def test_delete_session_endpoint_awaits_cleanup(client, monkeypatch):
    """Deleting a session should await service cleanup so wrap-up can run."""

    class FakeService:
        def __init__(self) -> None:
            self.deleted_ids: list[str] = []

        async def delete_session(self, session_id: str) -> bool:
            self.deleted_ids.append(session_id)
            return True

    service = FakeService()
    monkeypatch.setattr(sessions_api, "get_agent_service", lambda: service)

    response = client.delete("/api/sessions/session-123")

    assert response.status_code == 204
    assert service.deleted_ids == ["session-123"]
