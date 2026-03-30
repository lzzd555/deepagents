"""RPA skill service for creating and executing RPA skills."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deepagents_web.extensions.settings import WebSettings

from deepagents_web.models.rpa import RPAExecutionResult, RPAWorkflow
from deepagents_web.models.skill import SkillResponse
from deepagents_web.rpa.engine import RPAEngine
from deepagents_web.services.skill_service import SkillService


class RPASkillService:
    """Service for managing RPA skills."""

    def __init__(self, agent_name: str = "agent") -> None:
        """Initialize the RPA skill service."""
        self.agent_name = agent_name
        self.settings = WebSettings.from_environment()
        self.skill_service = SkillService(agent_name=agent_name)
        self.engine = RPAEngine()

    def create_rpa_skill(
        self,
        name: str,
        workflow: RPAWorkflow,
        *,
        project: bool = False,
    ) -> SkillResponse:
        """Create a new RPA skill."""
        # Validate name
        self.skill_service._validate_name(name)

        # Determine skills directory
        if project:
            if not self.settings.project_root:
                msg = "Not in a project directory"
                raise ValueError(msg)
            skills_dir = self.settings.ensure_project_skills_dir()
        else:
            skills_dir = self.settings.ensure_user_skills_dir(self.agent_name)

        if skills_dir is None:
            msg = "Could not determine skills directory"
            raise ValueError(msg)

        skill_dir = skills_dir / name
        if skill_dir.exists():
            msg = f"Skill '{name}' already exists"
            raise ValueError(msg)

        skill_dir.mkdir(parents=True, exist_ok=True)

        # Generate SKILL.md content
        skill_content = self._generate_rpa_skill_md(name, workflow)

        # Write SKILL.md
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_content, encoding="utf-8")

        # Write workflow.json
        workflow_json = skill_dir / "workflow.json"
        workflow_json.write_text(
            workflow.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return SkillResponse(
            name=name,
            description=workflow.description,
            path=str(skill_md),
            source="project" if project else "user",
            type="rpa",
            content=skill_content,
        )

    def get_rpa_skill(self, name: str) -> tuple[SkillResponse | None, RPAWorkflow | None]:
        """Get an RPA skill by name with workflow."""
        skill = self.skill_service.get_skill(name)
        if not skill:
            return None, None

        # Check if it's an RPA skill
        if not self._is_rpa_skill(skill.content):
            return skill, None

        # Load workflow.json
        skill_dir = Path(skill.path).parent
        workflow_json = skill_dir / "workflow.json"

        if not workflow_json.exists():
            return skill, None

        workflow_data = json.loads(workflow_json.read_text(encoding="utf-8"))
        workflow = RPAWorkflow.model_validate(workflow_data)

        return skill, workflow

    def execute_rpa_skill(
        self,
        name: str,
        params: dict[str, Any] | None = None,
    ) -> RPAExecutionResult:
        """Execute an RPA skill."""
        skill, workflow = self.get_rpa_skill(name)

        if not skill:
            return RPAExecutionResult(
                success=False,
                error=f"Skill '{name}' not found",
            )

        if not workflow:
            return RPAExecutionResult(
                success=False,
                error=f"Skill '{name}' is not an RPA skill or has no workflow",
            )

        return self.engine.execute(workflow, params)

    def update_rpa_skill(
        self,
        name: str,
        workflow: RPAWorkflow,
    ) -> SkillResponse:
        """Update an existing RPA skill."""
        skill = self.skill_service.get_skill(name)
        if not skill:
            msg = f"Skill '{name}' not found"
            raise ValueError(msg)

        skill_dir = Path(skill.path).parent

        # Update SKILL.md
        skill_content = self._generate_rpa_skill_md(name, workflow)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_content, encoding="utf-8")

        # Update workflow.json
        workflow_json = skill_dir / "workflow.json"
        workflow_json.write_text(
            workflow.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return SkillResponse(
            name=name,
            description=workflow.description,
            path=str(skill_md),
            source=skill.source,
            type="rpa",
            content=skill_content,
        )

    def _is_rpa_skill(self, content: str | None) -> bool:
        """Check if skill content indicates an RPA skill."""
        if not content:
            return False

        import re

        import yaml

        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if match:
            try:
                frontmatter = yaml.safe_load(match.group(1))
                return frontmatter.get("type") == "rpa"
            except yaml.YAMLError:
                pass
        return False

    def _generate_rpa_skill_md(self, name: str, workflow: RPAWorkflow) -> str:
        """Generate SKILL.md content for RPA skill."""
        title = name.replace("-", " ").title()

        # Generate action descriptions
        actions_desc = self._describe_workflow_actions(workflow)

        # Generate input/output params description
        input_desc = ""
        if workflow.input_params:
            input_desc = "\n".join(
                f"- `{p.key}` ({p.type}): {p.value}" for p in workflow.input_params
            )

        output_desc = ""
        if workflow.output_params:
            output_desc = "\n".join(f"- `{p}`" for p in workflow.output_params)

        return f"""---
name: {name}
description: {workflow.description}
type: rpa
version: {workflow.version}
---

# {title}

## Description

{workflow.description}

## Input Parameters

{input_desc or "No input parameters."}

## Output Parameters

{output_desc or "No output parameters."}

## Workflow Actions

{actions_desc}

## Execution

This is an RPA skill that executes a workflow of automated actions.
The workflow is defined in `workflow.json` in this directory.

## When to Use

- When you need to automate this specific workflow
- When the user requests this action
"""

    def _describe_workflow_actions(self, workflow: RPAWorkflow) -> str:
        """Generate human-readable description of workflow actions."""
        if not workflow.actions:
            return "No actions defined."

        lines = []
        for i, action in enumerate(workflow.actions, 1):
            params_str = ", ".join(f"{p.key}={p.value!r}" for p in action.params)
            lines.append(f"{i}. **{action.type.value}**({params_str})")

            if action.output_var:
                lines.append(f"   → Output: `{action.output_var}`")

        return "\n".join(lines)
