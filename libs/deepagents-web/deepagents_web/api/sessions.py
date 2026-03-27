"""REST API endpoints for session management."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deepagents_web.api.chat import get_agent_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionResponse(BaseModel):
    """Response model for a session."""

    session_id: str


class SessionListResponse(BaseModel):
    """Response model for listing sessions."""

    sessions: list[str]


@router.get("")
async def list_sessions() -> SessionListResponse:
    """List all active sessions."""
    service = get_agent_service()
    return SessionListResponse(sessions=service.list_sessions())


@router.post("", status_code=201)
async def create_session() -> SessionResponse:
    """Create a new agent session."""
    service = get_agent_service()
    session_id = await service.create_session()
    return SessionResponse(session_id=session_id)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str) -> None:
    """Delete an agent session."""
    service = get_agent_service()
    if not await service.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
