"""Context utilities for finding project-level AGENTS.md and CONTEXT.md files."""

from __future__ import annotations

from pathlib import Path


def find_project_root(start_path: Path | None = None) -> Path | None:
    """Find the project root by looking for .git directory.

    Walks up the directory tree from start_path (or cwd) looking for a .git
    directory, which indicates the project root.
    """
    current = Path(start_path or Path.cwd()).resolve()

    for parent in [current, *list(current.parents)]:
        if (parent / ".git").exists():
            return parent

    return None


def find_project_agent_md(project_root: Path) -> list[Path]:
    """Find project-specific AGENTS.md and CONTEXT.md file(s).

    Checks two locations and returns ALL that exist:
    1. project_root/.deepagents/AGENTS.md and CONTEXT.md
    2. project_root/AGENTS.md and CONTEXT.md

    Returns:
        List of paths to project AGENTS.md and CONTEXT.md files.
    """
    paths: list[Path] = []

    # Check .deepagents/ directory (preferred)
    deepagents_dir = project_root / ".deepagents"
    if deepagents_dir.exists():
        for name in ["AGENTS.md", "CONTEXT.md"]:
            p = deepagents_dir / name
            if p.exists():
                paths.append(p)

    # Check root directory
    for name in ["AGENTS.md", "CONTEXT.md"]:
        p = project_root / name
        if p.exists() and p not in paths:
            paths.append(p)

    return paths
