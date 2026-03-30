"""Hybrid skill executor for executing multi-step hybrid skills."""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from deepagents_web.models.hybrid import (
    HybridExecutionResult,
    HybridSkillDefinition,
    HybridStep,
    HybridStepResult,
    HybridStepType,
    NaturalLanguageStep,
    RecordingStep,
    RPAStep,
    SkillRefStep,
)
from deepagents_web.models.skill import SkillResponse


class HybridExecutionContext:
    """Execution context for hybrid skills with variable management."""

    def __init__(self, initial_params: dict[str, Any] | None = None) -> None:
        """Initialize the execution context."""
        self._variables: dict[str, Any] = initial_params.copy() if initial_params else {}
        self._step_results: list[HybridStepResult] = []

    def get_variable(self, name: str) -> Any:
        """Get a variable from the context."""
        return self._variables.get(name)

    def set_variable(self, name: str, value: Any) -> None:
        """Set a variable in the context."""
        self._variables[name] = value

    def get_all_variables(self) -> dict[str, Any]:
        """Get all variables in the context."""
        return self._variables.copy()

    def add_step_result(self, result: HybridStepResult) -> None:
        """Add a step result to the context."""
        self._step_results.append(result)

    def get_step_results(self) -> list[HybridStepResult]:
        """Get all step results."""
        return self._step_results.copy()

    def resolve_input_mappings(self, step: HybridStep) -> dict[str, Any]:
        """Resolve input mappings for a step."""
        resolved: dict[str, Any] = {}
        for mapping in step.input_mappings:
            value = self.get_variable(mapping.source_var)
            if value is not None:
                resolved[mapping.target_param] = value
        return resolved


class HybridSkillExecutor:
    """Execute hybrid skills step by step."""

    def __init__(self) -> None:
        """Initialize the hybrid skill executor."""
        self._executor = ThreadPoolExecutor(max_workers=2)

    async def execute(
        self,
        definition: HybridSkillDefinition,
        params: dict[str, Any] | None = None,
        skill_path: str | None = None,
    ) -> HybridExecutionResult:
        """Execute a hybrid skill."""
        start_time = time.time()
        context = HybridExecutionContext(params)

        try:
            for step in definition.steps:
                step_result = await self._execute_step(step, context, skill_path)
                context.add_step_result(step_result)

                # Store output variable if specified
                if step.output_var and step_result.output is not None:
                    context.set_variable(step.output_var, step_result.output)

                # Check for failure
                if not step_result.success and not step.skip_on_error:
                    return HybridExecutionResult(
                        success=False,
                        output=context.get_all_variables(),
                        error=f"Step '{step.name}' failed: {step_result.error}",
                        duration=time.time() - start_time,
                        step_results=context.get_step_results(),
                    )

            # Build output from output_params
            output = self._build_output(definition, context)

            return HybridExecutionResult(
                success=True,
                output=output,
                duration=time.time() - start_time,
                step_results=context.get_step_results(),
            )

        except Exception as e:  # noqa: BLE001
            return HybridExecutionResult(
                success=False,
                output=context.get_all_variables(),
                error=str(e),
                duration=time.time() - start_time,
                step_results=context.get_step_results(),
            )

    async def _execute_step(
        self,
        step: HybridStep,
        context: HybridExecutionContext,
        skill_path: str | None,
    ) -> HybridStepResult:
        """Execute a single step."""
        start_time = time.time()

        # Apply delay before
        if step.delay_before > 0:
            await asyncio.sleep(step.delay_before)

        # Resolve input mappings
        resolved_inputs = context.resolve_input_mappings(step)

        # Execute with retry logic
        last_error: str | None = None
        for attempt in range(step.retry_count + 1):
            try:
                result = await self._dispatch_step(step, resolved_inputs, skill_path)

                # Apply delay after
                if step.delay_after > 0:
                    await asyncio.sleep(step.delay_after)

                return HybridStepResult(
                    step_id=step.id,
                    step_type=step.type,
                    success=True,
                    output=result,
                    duration=time.time() - start_time,
                )

            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                if attempt < step.retry_count:
                    await asyncio.sleep(step.retry_interval)

        return HybridStepResult(
            step_id=step.id,
            step_type=step.type,
            success=False,
            error=last_error,
            duration=time.time() - start_time,
        )

    async def _dispatch_step(
        self,
        step: HybridStep,
        inputs: dict[str, Any],
        skill_path: str | None,
    ) -> Any:
        """Dispatch step execution based on type."""
        if step.type == HybridStepType.RECORDING:
            return await self._execute_recording_step(step, inputs, skill_path)  # type: ignore[arg-type]
        elif step.type == HybridStepType.NL:
            return await self._execute_nl_step(step, inputs)  # type: ignore[arg-type]
        elif step.type == HybridStepType.RPA:
            return await self._execute_rpa_step(step, inputs, skill_path)  # type: ignore[arg-type]
        elif step.type == HybridStepType.SKILL_REF:
            return await self._execute_skill_ref_step(step, inputs)  # type: ignore[arg-type]
        else:
            msg = f"Unknown step type: {step.type}"
            raise ValueError(msg)

    async def _execute_recording_step(
        self,
        step: RecordingStep,
        inputs: dict[str, Any],
        skill_path: str | None,
    ) -> Any:
        """Execute a recording step."""
        import os

        from deepagents_web.services.recording_service import RecordingService

        # If actions are stored directly in the step, execute them
        if step.actions:
            recording_service = RecordingService()
            # Execute the recorded actions
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self._executor,
                recording_service.execute_actions,
                step.actions,
                step.start_url,
                inputs,
            )
            return result

        # Find script path (fallback for script-based execution)
        script_path: Path | None = None

        if step.script_path:
            script_path = Path(step.script_path)
        elif skill_path:
            # Look for script in step directory
            skill_dir = Path(skill_path).parent
            step_dir = skill_dir / "steps" / f"{step.id}_recording"
            if step_dir.exists():
                script_path = step_dir / "script.py"

        if not script_path or not script_path.exists():
            msg = f"Recording actions or script not found for step '{step.name}'"
            raise FileNotFoundError(msg)

        # Execute script
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # Pass inputs as environment variables
        for key, value in inputs.items():
            env[f"HYBRID_INPUT_{key.upper()}"] = json.dumps(value) if not isinstance(value, str) else value

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self._executor,
            self._run_script,
            script_path,
            env,
        )

        return result

    async def _execute_nl_step(
        self,
        step: NaturalLanguageStep,
        inputs: dict[str, Any],
    ) -> Any:
        """Execute a natural language step using LLM."""
        from deepagents_web.extensions.models import create_model

        # Build prompt with instructions and inputs
        prompt_parts = [step.instructions]

        if inputs:
            prompt_parts.append("\n\nInput variables:")
            for key, value in inputs.items():
                prompt_parts.append(f"- {key}: {value}")

        if step.context_hints:
            prompt_parts.append("\n\nContext hints:")
            for hint in step.context_hints:
                prompt_parts.append(f"- {hint}")

        prompt = "\n".join(prompt_parts)

        model = create_model()
        response = await model.ainvoke([{"role": "user", "content": prompt}])
        content = response.content if hasattr(response, "content") else str(response)

        return content

    async def _execute_rpa_step(
        self,
        step: RPAStep,
        inputs: dict[str, Any],
        skill_path: str | None,
    ) -> Any:
        """Execute an RPA workflow step."""
        from deepagents_web.models.rpa import RPAWorkflow
        from deepagents_web.rpa.engine import RPAEngine

        workflow: RPAWorkflow | None = None

        # Load workflow from inline definition or file
        if step.workflow:
            workflow = RPAWorkflow.model_validate(step.workflow)
        elif step.workflow_path:
            workflow_path = Path(step.workflow_path)
            if workflow_path.exists():
                workflow_data = json.loads(workflow_path.read_text(encoding="utf-8"))
                workflow = RPAWorkflow.model_validate(workflow_data)
        elif skill_path:
            # Look for workflow in step directory
            skill_dir = Path(skill_path).parent
            step_dir = skill_dir / "steps" / f"{step.id}_rpa"
            workflow_file = step_dir / "workflow.json"
            if workflow_file.exists():
                workflow_data = json.loads(workflow_file.read_text(encoding="utf-8"))
                workflow = RPAWorkflow.model_validate(workflow_data)

        if not workflow:
            msg = f"RPA workflow not found for step '{step.name}'"
            raise FileNotFoundError(msg)

        # Execute workflow
        engine = RPAEngine()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self._executor,
            engine.execute,
            workflow,
            inputs,
        )

        if not result.success:
            msg = result.error or "RPA execution failed"
            raise RuntimeError(msg)

        return result.output

    async def _execute_skill_ref_step(
        self,
        step: SkillRefStep,
        inputs: dict[str, Any],
    ) -> Any:
        """Execute a skill reference step."""
        from deepagents_web.services.skill_executor import SkillExecutor
        from deepagents_web.services.skill_service import SkillService

        skill_service = SkillService()
        skill = skill_service.get_skill(step.skill_name)

        if not skill:
            msg = f"Referenced skill '{step.skill_name}' not found"
            raise FileNotFoundError(msg)

        # Merge inputs with param overrides
        merged_params = {**inputs, **step.param_overrides}

        # Check if it's a hybrid skill and execute recursively
        if self._is_hybrid_skill(skill):
            return await self._execute_nested_hybrid(skill, merged_params)

        # Execute as regular skill
        executor = SkillExecutor()
        result = await executor.execute_skill(skill)

        if not result.success:
            msg = result.error or "Skill execution failed"
            raise RuntimeError(msg)

        return result.output

    def _is_hybrid_skill(self, skill: SkillResponse) -> bool:
        """Check if a skill is a hybrid skill."""
        import re

        import yaml

        if not skill.content:
            return False

        match = re.match(r"^---\s*\n(.*?)\n---", skill.content, re.DOTALL)
        if match:
            try:
                frontmatter = yaml.safe_load(match.group(1))
                return frontmatter.get("type") == "hybrid"
            except yaml.YAMLError:
                pass
        return False

    async def _execute_nested_hybrid(
        self,
        skill: SkillResponse,
        params: dict[str, Any],
    ) -> Any:
        """Execute a nested hybrid skill."""
        from deepagents_web.services.hybrid_service import HybridSkillService

        service = HybridSkillService()
        _, definition = service.get_hybrid_skill(skill.name)

        if not definition:
            msg = f"Could not load hybrid skill definition for '{skill.name}'"
            raise ValueError(msg)

        result = await self.execute(definition, params, skill.path)

        if not result.success:
            msg = result.error or "Nested hybrid skill execution failed"
            raise RuntimeError(msg)

        return result.output

    def _run_script(self, script_path: Path, env: dict[str, str]) -> Any:
        """Run a Python script and return parsed output."""
        import subprocess

        process = subprocess.Popen(  # noqa: S603
            ["python", "-u", str(script_path)],  # noqa: S607
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=script_path.parent,
            env=env,
        )

        try:
            stdout_bytes, stderr_bytes = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
            msg = "Script execution timed out"
            raise RuntimeError(msg) from None

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        if process.returncode != 0:
            error_msg = stderr.strip() if stderr else "Script execution failed"
            raise RuntimeError(error_msg)

        stdout = stdout.strip()
        if not stdout:
            msg = f"Script produced no output. stderr: {stderr.strip()}"
            raise RuntimeError(msg)

        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {"message": stdout[:2000]}

    def _build_output(
        self,
        definition: HybridSkillDefinition,
        context: HybridExecutionContext,
    ) -> dict[str, Any]:
        """Build output from output_params specification."""
        if not definition.output_params:
            return context.get_all_variables()

        output: dict[str, Any] = {}
        for param in definition.output_params:
            value = context.get_variable(param)
            if value is not None:
                output[param] = value

        return output
