"""Hybrid skill service for creating and managing hybrid skills."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from deepagents_web.extensions.settings import WebSettings

from deepagents_web.models.hybrid import (
    HybridSkillDefinition,
    HybridSkillResponse,
    HybridStep,
    HybridStepType,
    NaturalLanguageStep,
    RecordingStep,
    RPAStep,
    SkillRefStep,
    VariableMapping,
)
from deepagents_web.models.skill import SkillResponse
from deepagents_web.services.skill_service import SkillService


class HybridSkillService:
    """Service for managing hybrid skills."""

    def __init__(self, agent_name: str = "agent") -> None:
        """Initialize the hybrid skill service."""
        self.agent_name = agent_name
        self.settings = WebSettings.from_environment()
        self.skill_service = SkillService(agent_name=agent_name)

    def create_hybrid_skill(
        self,
        name: str,
        description: str = "",
        input_params: list[dict[str, Any]] | None = None,
        steps: list[dict[str, Any]] | None = None,
        output_params: list[str] | None = None,
        *,
        project: bool = False,
    ) -> HybridSkillResponse:
        """Create a new hybrid skill."""
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

        # Create steps directory
        steps_dir = skill_dir / "steps"
        steps_dir.mkdir(exist_ok=True)

        # Process and validate steps
        processed_steps = self._process_steps(steps or [], steps_dir)

        # Create definition
        definition = HybridSkillDefinition(
            name=name,
            description=description,
            input_params=input_params or [],
            steps=processed_steps,
            output_params=output_params or [],
        )

        # Generate SKILL.md content
        skill_content = self._generate_hybrid_skill_md(definition)

        # Write SKILL.md
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_content, encoding="utf-8")

        # Write definition.json
        definition_json = skill_dir / "definition.json"
        definition_json.write_text(
            definition.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return HybridSkillResponse(
            name=name,
            description=description,
            path=str(skill_md),
            version=definition.version,
            input_params=definition.input_params,
            steps=[s.model_dump() for s in definition.steps],
            output_params=definition.output_params,
        )

    def get_hybrid_skill(
        self, name: str
    ) -> tuple[SkillResponse | None, HybridSkillDefinition | None]:
        """Get a hybrid skill by name with definition."""
        skill = self.skill_service.get_skill(name)
        if not skill:
            return None, None

        # Check if it's a hybrid skill
        if not self._is_hybrid_skill(skill.content):
            return skill, None

        # Load definition.json
        skill_dir = Path(skill.path).parent
        definition_json = skill_dir / "definition.json"

        if not definition_json.exists():
            return skill, None

        definition_data = json.loads(definition_json.read_text(encoding="utf-8"))
        definition = HybridSkillDefinition.model_validate(definition_data)

        return skill, definition

    def update_hybrid_skill(
        self,
        name: str,
        description: str | None = None,
        input_params: list[dict[str, Any]] | None = None,
        steps: list[dict[str, Any]] | None = None,
        output_params: list[str] | None = None,
    ) -> HybridSkillResponse:
        """Update an existing hybrid skill."""
        skill, definition = self.get_hybrid_skill(name)

        if not skill:
            msg = f"Skill '{name}' not found"
            raise ValueError(msg)

        if not definition:
            msg = f"Skill '{name}' is not a hybrid skill"
            raise ValueError(msg)

        skill_dir = Path(skill.path).parent
        steps_dir = skill_dir / "steps"
        steps_dir.mkdir(exist_ok=True)

        # Update fields
        if description is not None:
            definition.description = description
        if input_params is not None:
            definition.input_params = input_params
        if steps is not None:
            definition.steps = self._process_steps(steps, steps_dir)
        if output_params is not None:
            definition.output_params = output_params

        # Update SKILL.md
        skill_content = self._generate_hybrid_skill_md(definition)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_content, encoding="utf-8")

        # Update definition.json
        definition_json = skill_dir / "definition.json"
        definition_json.write_text(
            definition.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return HybridSkillResponse(
            name=name,
            description=definition.description,
            path=str(skill_md),
            version=definition.version,
            input_params=definition.input_params,
            steps=[s.model_dump() for s in definition.steps],
            output_params=definition.output_params,
        )

    def delete_hybrid_skill(self, name: str) -> None:
        """Delete a hybrid skill."""
        self.skill_service.delete_skill(name)

    def add_step(
        self,
        skill_name: str,
        step_type: HybridStepType,
        step_name: str,
        description: str = "",
        data: dict[str, Any] | None = None,
        input_mappings: list[dict[str, str]] | None = None,
        output_var: str | None = None,
        skip_on_error: bool = False,
        retry_count: int = 0,
        position: int | None = None,
    ) -> HybridSkillResponse:
        """Add a step to a hybrid skill."""
        skill, definition = self.get_hybrid_skill(skill_name)

        if not skill:
            msg = f"Skill '{skill_name}' not found"
            raise ValueError(msg)

        if not definition:
            msg = f"Skill '{skill_name}' is not a hybrid skill"
            raise ValueError(msg)

        skill_dir = Path(skill.path).parent
        steps_dir = skill_dir / "steps"
        steps_dir.mkdir(exist_ok=True)

        # Create step
        step = self._create_step(
            step_type=step_type,
            name=step_name,
            description=description,
            data=data or {},
            input_mappings=input_mappings or [],
            output_var=output_var,
            skip_on_error=skip_on_error,
            retry_count=retry_count,
            steps_dir=steps_dir,
        )

        # Add step at position or append
        if position is not None and 0 <= position <= len(definition.steps):
            definition.steps.insert(position, step)
        else:
            definition.steps.append(step)

        # Update files
        skill_content = self._generate_hybrid_skill_md(definition)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_content, encoding="utf-8")

        definition_json = skill_dir / "definition.json"
        definition_json.write_text(
            definition.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return HybridSkillResponse(
            name=skill_name,
            description=definition.description,
            path=str(skill_md),
            version=definition.version,
            input_params=definition.input_params,
            steps=[s.model_dump() for s in definition.steps],
            output_params=definition.output_params,
        )

    def remove_step(self, skill_name: str, step_id: str) -> HybridSkillResponse:
        """Remove a step from a hybrid skill."""
        skill, definition = self.get_hybrid_skill(skill_name)

        if not skill:
            msg = f"Skill '{skill_name}' not found"
            raise ValueError(msg)

        if not definition:
            msg = f"Skill '{skill_name}' is not a hybrid skill"
            raise ValueError(msg)

        # Find and remove step
        step_index = next(
            (i for i, s in enumerate(definition.steps) if s.id == step_id),
            None,
        )

        if step_index is None:
            msg = f"Step '{step_id}' not found in skill '{skill_name}'"
            raise ValueError(msg)

        definition.steps.pop(step_index)

        # Update files
        skill_dir = Path(skill.path).parent
        skill_content = self._generate_hybrid_skill_md(definition)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_content, encoding="utf-8")

        definition_json = skill_dir / "definition.json"
        definition_json.write_text(
            definition.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return HybridSkillResponse(
            name=skill_name,
            description=definition.description,
            path=str(skill_md),
            version=definition.version,
            input_params=definition.input_params,
            steps=[s.model_dump() for s in definition.steps],
            output_params=definition.output_params,
        )

    def reorder_steps(
        self, skill_name: str, step_ids: list[str]
    ) -> HybridSkillResponse:
        """Reorder steps in a hybrid skill."""
        skill, definition = self.get_hybrid_skill(skill_name)

        if not skill:
            msg = f"Skill '{skill_name}' not found"
            raise ValueError(msg)

        if not definition:
            msg = f"Skill '{skill_name}' is not a hybrid skill"
            raise ValueError(msg)

        # Create mapping of step_id to step
        step_map = {s.id: s for s in definition.steps}

        # Validate all step_ids exist
        for step_id in step_ids:
            if step_id not in step_map:
                msg = f"Step '{step_id}' not found in skill '{skill_name}'"
                raise ValueError(msg)

        # Reorder steps
        definition.steps = [step_map[step_id] for step_id in step_ids]

        # Update files
        skill_dir = Path(skill.path).parent
        skill_content = self._generate_hybrid_skill_md(definition)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_content, encoding="utf-8")

        definition_json = skill_dir / "definition.json"
        definition_json.write_text(
            definition.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return HybridSkillResponse(
            name=skill_name,
            description=definition.description,
            path=str(skill_md),
            version=definition.version,
            input_params=definition.input_params,
            steps=[s.model_dump() for s in definition.steps],
            output_params=definition.output_params,
        )

    def list_hybrid_skills(self, *, project_only: bool = False) -> list[HybridSkillResponse]:
        """List all hybrid skills."""
        all_skills = self.skill_service.list_skills(project_only=project_only)
        hybrid_skills = []

        for skill in all_skills:
            if self._is_hybrid_skill(skill.content):
                _, definition = self.get_hybrid_skill(skill.name)
                if definition:
                    hybrid_skills.append(
                        HybridSkillResponse(
                            name=skill.name,
                            description=definition.description,
                            path=skill.path,
                            version=definition.version,
                            input_params=definition.input_params,
                            steps=[s.model_dump() for s in definition.steps],
                            output_params=definition.output_params,
                        )
                    )

        return hybrid_skills

    def _is_hybrid_skill(self, content: str | None) -> bool:
        """Check if skill content indicates a hybrid skill."""
        if not content:
            return False

        import re

        import yaml

        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if match:
            try:
                frontmatter = yaml.safe_load(match.group(1))
                return frontmatter.get("type") == "hybrid"
            except yaml.YAMLError:
                pass
        return False

    def _process_steps(
        self, steps_data: list[dict[str, Any]], steps_dir: Path
    ) -> list[HybridStep]:
        """Process and validate step data."""
        processed_steps: list[HybridStep] = []

        for i, step_data in enumerate(steps_data):
            step_type = HybridStepType(step_data.get("type", "nl"))
            step = self._create_step(
                step_type=step_type,
                name=step_data.get("name", f"Step {i + 1}"),
                description=step_data.get("description", ""),
                data=step_data.get("data", {}),
                input_mappings=step_data.get("input_mappings", []),
                output_var=step_data.get("output_var"),
                skip_on_error=step_data.get("skip_on_error", False),
                retry_count=step_data.get("retry_count", 0),
                steps_dir=steps_dir,
                step_id=step_data.get("id"),
            )
            processed_steps.append(step)

        return processed_steps

    def _create_step(
        self,
        step_type: HybridStepType,
        name: str,
        description: str,
        data: dict[str, Any],
        input_mappings: list[dict[str, str]],
        output_var: str | None,
        skip_on_error: bool,
        retry_count: int,
        steps_dir: Path,
        step_id: str | None = None,
    ) -> HybridStep:
        """Create a step of the specified type."""
        # Generate step ID if not provided
        if not step_id:
            step_id = f"step_{uuid.uuid4().hex[:8]}"

        # Convert input mappings
        mappings = [
            VariableMapping(source_var=m["source_var"], target_param=m["target_param"])
            for m in input_mappings
        ]

        # Common step attributes
        common_attrs = {
            "id": step_id,
            "name": name,
            "description": description,
            "input_mappings": mappings,
            "output_var": output_var,
            "skip_on_error": skip_on_error,
            "retry_count": retry_count,
            "delay_before": data.get("delay_before", 0),
            "delay_after": data.get("delay_after", 0),
            "retry_interval": data.get("retry_interval", 1.0),
        }

        if step_type == HybridStepType.RECORDING:
            # Save actions to file if provided
            actions = data.get("actions", [])
            if actions:
                step_dir = steps_dir / f"{step_id}_recording"
                step_dir.mkdir(exist_ok=True)
                actions_file = step_dir / "actions.json"
                actions_file.write_text(
                    json.dumps(actions, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

            return RecordingStep(
                **common_attrs,
                session_id=data.get("session_id"),
                script_path=data.get("script_path"),
                actions=actions,
                start_url=data.get("start_url"),
            )
        elif step_type == HybridStepType.NL:
            # Create instructions file if provided
            instructions = data.get("instructions", "")
            if instructions:
                step_dir = steps_dir / f"{step_id}_nl"
                step_dir.mkdir(exist_ok=True)
                instructions_file = step_dir / "instructions.md"
                instructions_file.write_text(instructions, encoding="utf-8")

            return NaturalLanguageStep(
                **common_attrs,
                instructions=instructions,
                context_hints=data.get("context_hints", []),
            )
        elif step_type == HybridStepType.RPA:
            # Save workflow if provided
            workflow = data.get("workflow")
            workflow_path = data.get("workflow_path")
            if workflow and not workflow_path:
                step_dir = steps_dir / f"{step_id}_rpa"
                step_dir.mkdir(exist_ok=True)
                workflow_file = step_dir / "workflow.json"
                workflow_file.write_text(
                    json.dumps(workflow, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                workflow_path = str(workflow_file)

            return RPAStep(
                **common_attrs,
                workflow=workflow,
                workflow_path=workflow_path,
            )
        elif step_type == HybridStepType.SKILL_REF:
            return SkillRefStep(
                **common_attrs,
                skill_name=data.get("skill_name", ""),
                param_overrides=data.get("param_overrides", {}),
            )
        else:
            msg = f"Unknown step type: {step_type}"
            raise ValueError(msg)

    def _generate_hybrid_skill_md(self, definition: HybridSkillDefinition) -> str:
        """Generate SKILL.md content for hybrid skill."""
        title = definition.name.replace("-", " ").title()

        # Generate steps description
        steps_desc = self._describe_steps(definition.steps)

        # Generate input/output params description
        input_desc = ""
        if definition.input_params:
            input_desc = "\n".join(
                f"- `{p.get('name', 'param')}` ({p.get('type', 'string')}): {p.get('description', '')}"
                for p in definition.input_params
            )

        output_desc = ""
        if definition.output_params:
            output_desc = "\n".join(f"- `{p}`" for p in definition.output_params)

        return f"""---
name: {definition.name}
description: {definition.description}
type: hybrid
version: {definition.version}
---

# {title}

## Description

{definition.description}

## Input Parameters

{input_desc or "No input parameters."}

## Output Parameters

{output_desc or "No output parameters."}

## Steps

{steps_desc}

## Execution

This is a hybrid skill that combines multiple automation methods.
The workflow definition is stored in `definition.json` in this directory.

## When to Use

- When you need to execute this multi-step workflow
- When the user requests this action
"""

    def _describe_steps(self, steps: list[HybridStep]) -> str:
        """Generate human-readable description of steps."""
        if not steps:
            return "No steps defined."

        lines = []
        for i, step in enumerate(steps, 1):
            step_type_label = {
                HybridStepType.RECORDING: "Recording",
                HybridStepType.NL: "Natural Language",
                HybridStepType.RPA: "RPA Workflow",
                HybridStepType.SKILL_REF: "Skill Reference",
            }.get(step.type, step.type.value)

            lines.append(f"{i}. **{step.name}** ({step_type_label})")
            if step.description:
                lines.append(f"   {step.description}")

            if step.input_mappings:
                mappings = ", ".join(
                    f"{m.source_var} → {m.target_param}" for m in step.input_mappings
                )
                lines.append(f"   Inputs: {mappings}")

            if step.output_var:
                lines.append(f"   Output: `{step.output_var}`")

            lines.append("")

        return "\n".join(lines)
