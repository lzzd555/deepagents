"""Tests for chat frontend session cleanup behavior."""

from pathlib import Path


def test_chat_js_closes_session_on_page_exit() -> None:
    """Chat frontend should explicitly delete sessions on page unload."""
    chat_js = (
        Path(__file__).resolve().parents[1]
        / "deepagents_web"
        / "static"
        / "js"
        / "chat.js"
    ).read_text(encoding="utf-8")

    assert "window.addEventListener('pagehide'" in chat_js
    assert "window.addEventListener('beforeunload'" in chat_js
    assert "fetch(`/api/sessions/${this.sessionId}`" in chat_js
    assert "method: 'DELETE'" in chat_js
    assert "keepalive: true" in chat_js
