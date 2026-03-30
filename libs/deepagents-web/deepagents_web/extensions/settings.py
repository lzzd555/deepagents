"""Lightweight settings for deepagents-web, replacing deepagents_cli.config.Settings."""

from __future__ import annotations

from pathlib import Path

from deepagents_web.extensions.context_utils import find_project_root


class WebSettings:
    """Minimal path-management settings for deepagents-web.

    Replaces ``deepagents_cli.config.Settings`` with just the path helpers
    that the web service actually uses.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root

    @classmethod
    def from_environment(cls) -> WebSettings:
        """Create settings, auto-detecting project root from the cwd."""
        return cls(project_root=find_project_root())

    # -- project root -------------------------------------------------------

    @property
    def project_root(self) -> Path | None:
        return self._project_root

    # -- agent directory -----------------------------------------------------

    def get_agent_dir(self, name: str) -> Path:
        return Path.home() / ".deepagents" / name

    def ensure_agent_dir(self, name: str) -> Path:
        d = self.get_agent_dir(name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- user skills ---------------------------------------------------------

    def get_user_skills_dir(self, name: str) -> Path:
        return Path.home() / ".deepagents" / name / "skills"

    def ensure_user_skills_dir(self, name: str) -> Path:
        d = self.get_user_skills_dir(name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- project skills ------------------------------------------------------

    def get_project_skills_dir(self) -> Path | None:
        if self._project_root is None:
            return None
        return self._project_root / ".deepagents" / "skills"

    def ensure_project_skills_dir(self) -> Path | None:
        d = self.get_project_skills_dir()
        if d is None:
            return None
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- AGENTS.md paths -----------------------------------------------------

    def get_user_agent_md_path(self, name: str) -> Path:
        return self.get_agent_dir(name) / "AGENTS.md"

    def get_project_agent_md_path(self) -> Path | None:
        if self._project_root is None:
            return None
        # Prefer .deepagents/AGENTS.md, fall back to root AGENTS.md
        da_md = self._project_root / ".deepagents" / "AGENTS.md"
        if da_md.exists():
            return da_md
        root_md = self._project_root / "AGENTS.md"
        if root_md.exists():
            return root_md
        return None


# Module-level singleton (lazy)
_settings: WebSettings | None = None


def get_settings() -> WebSettings:
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = WebSettings.from_environment()
    return _settings


# Convenient alias used by callers that previously did ``from deepagents_cli.config import settings``.
settings = get_settings()
