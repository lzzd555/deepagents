"""Skill listing utilities, replacing deepagents_cli.skills.load.list_skills."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def _parse_skill_md(skill_md: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a SKILL.md file.

    Returns a dict with at least ``name``, ``description``, ``path``,
    and ``source``, or ``None`` if the file is invalid.
    """
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None

    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None

    if not isinstance(frontmatter, dict):
        return None

    return {
        "name": frontmatter.get("name", skill_md.parent.name),
        "description": frontmatter.get("description", ""),
        "path": str(skill_md),
        "type": frontmatter.get("type"),
    }


def _scan_skills_dir(skills_dir: Path, source: str) -> list[dict[str, Any]]:
    """Scan a directory for skill subdirectories containing SKILL.md."""
    if not skills_dir.exists():
        return []

    skills: list[dict[str, Any]] = []
    try:
        entries = list(skills_dir.iterdir())
    except OSError:
        return []

    for entry in entries:
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        parsed = _parse_skill_md(skill_md)
        if parsed is not None:
            parsed["source"] = source
            skills.append(parsed)

    return skills


def list_skills(
    *,
    user_skills_dir: Path | None = None,
    project_skills_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """List skills from user and project directories.

    Replaces ``deepagents_cli.skills.load.list_skills`` with a simplified
    version that only handles user and project skill directories (no built-in
    skills, which are a CLI-only concept).
    """
    seen: dict[str, dict[str, Any]] = {}

    # User skills first (lower precedence)
    if user_skills_dir is not None:
        for skill in _scan_skills_dir(user_skills_dir, source="user"):
            seen[skill["name"]] = skill

    # Project skills override user skills of the same name
    if project_skills_dir is not None:
        for skill in _scan_skills_dir(project_skills_dir, source="project"):
            seen[skill["name"]] = skill

    return list(seen.values())
