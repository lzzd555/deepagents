"""Skill service for CRUD operations."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from deepagents_web.extensions.settings import WebSettings
from deepagents_web.extensions.skills import list_skills

from deepagents_web.models.recording import ActionType, RecordedAction
from deepagents_web.models.skill import MAX_SKILL_NAME_LENGTH, SkillResponse

if TYPE_CHECKING:
    from deepagents_web.models.recording import RecordingSession


class SkillService:
    """Service for managing skills."""

    def __init__(self, agent_name: str = "agent") -> None:
        """Initialize the skill service."""
        self.agent_name = agent_name
        self.settings = WebSettings.from_environment()

    def _truncate(self, text: str, max_len: int = 80) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _run_coroutine_sync(self, coro: object) -> object:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)  # type: ignore[arg-type]

        import threading

        result: dict[str, object] = {}
        error: dict[str, Exception] = {}

        def _runner() -> None:
            try:
                result["value"] = asyncio.run(coro)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                error["error"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        if "error" in error:
            raise error["error"]
        return result.get("value")

    def list_skills(self, *, project_only: bool = False) -> list[SkillResponse]:
        """List all skills."""
        user_skills_dir = (
            None if project_only else self.settings.get_user_skills_dir(self.agent_name)
        )
        project_skills_dir = self.settings.get_project_skills_dir()

        skills = list_skills(
            user_skills_dir=user_skills_dir,
            project_skills_dir=project_skills_dir,
        )

        responses: list[SkillResponse] = []
        for s in skills:
            skill_path = Path(s["path"])
            skill_type = self._get_skill_type_from_path(skill_path) or "manual"
            responses.append(
                SkillResponse(
                    name=s["name"],
                    description=s["description"],
                    path=s["path"],
                    source=s["source"],
                    type=skill_type,
                )
            )
        return responses

    def get_skill(self, name: str) -> SkillResponse | None:
        """Get a skill by name with full content."""
        skills = self.list_skills()
        skill = next((s for s in skills if s.name == name), None)
        if not skill:
            return None

        skill_path = Path(skill.path)
        if skill_path.exists():
            skill.content = skill_path.read_text(encoding="utf-8")
            skill.type = self._parse_skill_type(skill.content) or skill.type or "manual"
        return skill

    def create_skill(
        self,
        name: str,
        description: str,
        content: str | None = None,
        *,
        project: bool = False,
    ) -> SkillResponse:
        """Create a new skill."""
        self._validate_name(name)

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

        if content is None:
            content = self._get_template(name, description)

        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")

        skill_type = self._parse_skill_type(content) or "manual"
        return SkillResponse(
            name=name,
            description=description,
            path=str(skill_md),
            source="project" if project else "user",
            type=skill_type,
            content=content,
        )

    def update_skill(
        self,
        name: str,
        content: str,
        description: str | None = None,
    ) -> SkillResponse:
        """Update an existing skill."""
        skill = self.get_skill(name)
        if not skill:
            msg = f"Skill '{name}' not found"
            raise ValueError(msg)

        skill_path = Path(skill.path)
        skill_path.write_text(content, encoding="utf-8")

        skill_type = self._parse_skill_type(content) or "manual"
        return SkillResponse(
            name=name,
            description=description or skill.description,
            path=skill.path,
            source=skill.source,
            type=skill_type,
            content=content,
        )

    def delete_skill(self, name: str) -> None:
        """Delete a skill."""
        skill = self.get_skill(name)
        if not skill:
            msg = f"Skill '{name}' not found"
            raise ValueError(msg)

        skill_path = Path(skill.path)
        skill_dir = skill_path.parent
        shutil.rmtree(skill_dir)

    def _validate_name(self, name: str) -> None:
        """Validate skill name per Agent Skills spec."""
        if not name or not name.strip():
            msg = "name cannot be empty"
            raise ValueError(msg)
        if len(name) > MAX_SKILL_NAME_LENGTH:
            msg = "name cannot exceed 64 characters"
            raise ValueError(msg)
        if ".." in name or "/" in name or "\\" in name:
            msg = "name cannot contain path components"
            raise ValueError(msg)
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
            msg = "name must be lowercase alphanumeric with single hyphens only"
            raise ValueError(msg)

    def _get_template(self, name: str, description: str) -> str:
        """Get the default SKILL.md template."""
        title = name.title().replace("-", " ")
        return f"""---
name: {name}
description: {description}
---

# {title} Skill

## Description

{description}

## When to Use

- [Scenario 1: When the user asks...]
- [Scenario 2: When you need to...]

## How to Use

### Step 1: [First Action]
[Explain what to do first]

### Step 2: [Second Action]
[Explain what to do next]

## Best Practices

- [Best practice 1]
- [Best practice 2]
"""

    def _parse_skill_type(self, content: str | None) -> str | None:
        """Parse the skill type from YAML frontmatter."""
        if not content:
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

        skill_type = frontmatter.get("type")
        if isinstance(skill_type, str):
            skill_type = skill_type.strip()
            return skill_type or None
        return None

    def _get_skill_type_from_path(self, skill_path: Path) -> str | None:
        """Read SKILL.md and return its type from frontmatter."""
        try:
            content = skill_path.read_text(encoding="utf-8")
        except OSError:
            return None
        return self._parse_skill_type(content)

    async def create_skill_from_nl(
        self,
        name: str,
        goal: str,
        steps: str,
        *,
        project: bool = False,
    ) -> SkillResponse:
        """Create skill from natural language description using LLM."""
        self._validate_name(name)

        from deepagents_web.extensions.models import create_model

        prompt = f"""Generate a SKILL.md file for an agent skill with:

Name: {name}
Goal: {goal}
Steps: {steps}

The SKILL.md must have YAML frontmatter with 'name' and 'description' fields,
followed by markdown instructions. Include:
- When to Use section
- Step-by-step instructions
- Best practices

Output only the SKILL.md content, no explanation."""

        model = create_model()
        response = await model.ainvoke([{"role": "user", "content": prompt}])
        content = response.content if hasattr(response, "content") else str(response)

        if not content.startswith("---"):
            content = self._wrap_with_frontmatter(name, goal, content)

        return self.create_skill(name=name, description=goal, content=content, project=project)

    async def create_skill_from_recording(
        self,
        name: str,
        description: str,
        session: RecordingSession,
        *,
        project: bool = False,
    ) -> SkillResponse:
        """Create skill from recorded browser actions using LLM."""
        self._validate_name(name)

        from deepagents_web.extensions.models import create_model

        # Convert recorded actions to description with robust selectors
        actions_desc = self._describe_recorded_actions(session.actions)

        # Use LLM to generate smart Playwright script with improved prompt
        prompt = f"""You are an expert at writing Playwright browser automation scripts.

Based on the following recorded browser actions, generate a robust Python script using Playwright.

## Task Description
{description}

        ## Recorded Actions
        {actions_desc}

        ## Critical: Use Recorded Locator Hints Exactly
        For each action, the recorded description may include structured hints like:
        - `role=...`, `name="..."`, `text="..."`
        - `css=...`, `xpath=...`

        When these hints are present:
        - Prefer them over guessing. Do not invent a different `role`/`name`.
        - Use `role`+`name` (or `text`) as the primary locator when available.
        - Keep `css`/`xpath` as fallbacks if the primary locator fails.

        ## Critical: Preserve Recorded Data Extraction Steps
        Some recorded actions are data extraction steps (e.g. `extract_text`, `extract_html`,
        `extract_attribute`, `execute_js`). The generated Python script MUST implement them
        (in order) and include their outputs in the final JSON result.

Requirements for data extraction actions:
- `extract_text`: locate the element, get `.text_content()`, store under the recorded
  `variable_name`
- `extract_html`: locate the element, get `.inner_html()`, store under the recorded
  `variable_name`
- `extract_attribute`: locate the element, get `.get_attribute(attribute_name)`, store
  under the recorded `variable_name`
- `execute_js`: run `page.evaluate(js_code)` and store result under the recorded
  `variable_name`

Output contract:
- Add a dict `extracted: dict[str, Any]` in the returned result JSON, containing all
  extracted variables.
- Do not drop these steps just because you also return general page content.

        ## Requirements
        1. Use playwright.sync_api with sync_playwright()
        2. Launch browser with headless=False so user can see the automation
        3. **CRITICAL: Use Playwright's recommended locator strategies in this priority order:**
   - page.get_by_role("button", name="Submit") - BEST for buttons, links, headings
   - page.get_by_text("Click me") - GOOD for text content
   - page.get_by_label("Email") - GOOD for form inputs with labels
   - page.get_by_placeholder("Enter email") - GOOD for inputs with placeholders
   - page.get_by_test_id("submit-btn") - GOOD if data-testid exists
   - page.locator("css=...") - LAST RESORT only
        4. Add proper waits after each action:
           - After navigation: page.wait_for_load_state('networkidle')
           - After clicks: page.wait_for_load_state('domcontentloaded')
           - For dynamic elements: expect(locator).to_be_visible()
        5. Handle potential timing issues with explicit waits
        6. Conditional result payload:
           - Always build `extracted: dict[str, Any]` with all recorded extracted variables
           - If `extracted` contains any meaningful (non-empty) values, return ONLY:
             `{{"extracted": extracted}}`
           - If `extracted` is empty, return page info for debugging:
             `url`, `title`, `content`, `links`, `tables`, `lists`
        7. Include comprehensive error handling with try/except
        8. The script must be self-contained and executable with `python script.py`
        9. Output result as JSON to stdout

## Result JSON Must Include Extracted Variables
Always build an `extracted` dict, and conditionally return only it when non-empty:

        ```python
        if extracted:
            result = {{"extracted": extracted}}
        else:
            result = {{
                "url": page.url,
                "title": page.title(),
                # ... content keys when no extraction happened
            }}
        ```

## CRITICAL: Main block must have try/except
The if __name__ == "__main__": block MUST wrap everything in try/except and print JSON:

```python
if __name__ == "__main__":
    try:
        result = run_skill()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        import traceback
        error_data = {{"error": str(e), "traceback": traceback.format_exc()}}
        print(json.dumps(error_data, ensure_ascii=False))
```

## Output Format
Output ONLY the Python code, no markdown code blocks, no explanations.
"""

        model = create_model()
        response = await model.ainvoke([{"role": "user", "content": prompt}])
        playwright_code = response.content if hasattr(response, "content") else str(response)

        # Clean up code if wrapped in markdown
        playwright_code = self._clean_code_block(playwright_code)

        # Ensure proper encoding header
        if "sys.stdout" not in playwright_code:
            encoding_header = """import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

"""
            playwright_code = encoding_header + playwright_code

        # Generate SKILL.md
        skill_content = self._generate_browser_skill_md(name, description, actions_desc)

        # Create skill directory and files
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

        # Write files
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_content, encoding="utf-8")

        script_py = skill_dir / "script.py"
        script_py.write_text(playwright_code, encoding="utf-8")

        skill_type = self._parse_skill_type(skill_content) or "manual"
        return SkillResponse(
            name=name,
            description=description,
            path=str(skill_md),
            source="project" if project else "user",
            type=skill_type,
            content=skill_content,
        )

    def _describe_recorded_actions(self, actions: list[RecordedAction]) -> str:
        """Convert recorded actions to human-readable description."""
        lines = []
        handlers = {
            ActionType.NAVIGATE: self._describe_navigate_action,
            ActionType.CLICK: self._describe_click_action,
            ActionType.FILL: self._describe_fill_action,
            ActionType.PRESS: self._describe_press_action,
            ActionType.SELECT: self._describe_select_action,
            ActionType.CHECK: self._describe_check_action,
            ActionType.UNCHECK: self._describe_uncheck_action,
            ActionType.EXTRACT: self._describe_extract_action,
            ActionType.EXTRACT_TEXT: self._describe_extract_text_action,
            ActionType.EXTRACT_HTML: self._describe_extract_html_action,
            ActionType.EXTRACT_ATTRIBUTE: self._describe_extract_attribute_action,
            ActionType.AI_EXTRACT: self._describe_ai_extract_action,
            ActionType.AI_FILL: self._describe_ai_fill_action,
            ActionType.EXECUTE_JS: self._describe_execute_js_action,
        }
        for i, action in enumerate(actions, 1):
            handler = handlers.get(action.type)
            if handler:
                lines.append(handler(i, action))
        return "\n".join(lines) if lines else "No actions recorded."

    def _describe_navigate_action(self, index: int, action: RecordedAction) -> str:
        return f"{index}. Navigate to URL: {action.value}"

    def _describe_click_action(self, index: int, action: RecordedAction) -> str:
        parts: list[str] = []

        if action.selector:
            parts.append(f"css={action.selector}")
        if action.xpath:
            parts.append(f"xpath={action.xpath}")

        if action.accessibility:
            if action.accessibility.role:
                parts.append(f"role={action.accessibility.role}")
            if action.accessibility.name:
                parts.append(f'name="{action.accessibility.name}"')

        if action.context:
            if action.context.form_hint:
                parts.append(f"form_hint={action.context.form_hint}")
            if action.context.ancestor_tags:
                ancestors = ">".join(action.context.ancestor_tags[:6])
                parts.append(f"ancestors={ancestors}")
            if action.context.nearby_text:
                nearby = " | ".join(action.context.nearby_text[:3])
                parts.append(f'nearby="{self._truncate(nearby, 90)}"')

        if action.evidence and action.evidence.confidence is not None:
            parts.append(f"confidence={action.evidence.confidence:.2f}")

        text = action.value.strip() if action.value else ""
        if text:
            parts.append(f'text="{text}"')

        element_desc = ", ".join(parts) if parts else "(unknown)"

        if action.x is not None and action.y is not None:
            return f"{index}. Click at ({action.x}, {action.y}), element: {element_desc}"
        return f"{index}. Click on element: {element_desc}"

    def _describe_fill_action(self, index: int, action: RecordedAction) -> str:
        return f'{index}. Fill input {action.selector} with: "{action.value}"'

    def _describe_press_action(self, index: int, action: RecordedAction) -> str:
        return f"{index}. Press key {action.value} on {action.selector}"

    def _describe_select_action(self, index: int, action: RecordedAction) -> str:
        return f"{index}. Select option {action.value} in {action.selector}"

    def _describe_check_action(self, index: int, action: RecordedAction) -> str:
        return f"{index}. Check checkbox: {action.selector}"

    def _describe_uncheck_action(self, index: int, action: RecordedAction) -> str:
        return f"{index}. Uncheck checkbox: {action.selector}"

    def _describe_extract_action(self, index: int, action: RecordedAction) -> str:
        selector = action.selector or action.xpath or ""
        variable = action.variable_name or action.output_key or "extracted"
        return f"{index}. Extract data from {selector} into {variable}"

    def _describe_extract_text_action(self, index: int, action: RecordedAction) -> str:
        selector = action.selector or action.xpath or ""
        variable = action.variable_name or action.output_key or "extracted_text"
        return f"{index}. Extract text from {selector} into {variable}"

    def _describe_extract_html_action(self, index: int, action: RecordedAction) -> str:
        selector = action.selector or action.xpath or ""
        variable = action.variable_name or action.output_key or "extracted_html"
        return f"{index}. Extract HTML from {selector} into {variable}"

    def _describe_extract_attribute_action(self, index: int, action: RecordedAction) -> str:
        selector = action.selector or action.xpath or ""
        variable = action.variable_name or action.output_key or "extracted"
        attr = action.attribute_name or "attribute"
        return f"{index}. Extract attribute '{attr}' from {selector} into {variable}"

    def _describe_ai_extract_action(self, index: int, action: RecordedAction) -> str:
        prompt = action.prompt or "AI extraction"
        output = action.output_key or action.variable_name or "ai_extracted"
        return f'{index}. AI extract "{prompt}" into {output}'

    def _describe_ai_fill_action(self, index: int, action: RecordedAction) -> str:
        prompt = action.prompt or "AI fill"
        selector = action.selector or action.xpath or ""
        return f'{index}. AI fill {selector} with "{prompt}"'

    def _describe_execute_js_action(self, index: int, action: RecordedAction) -> str:
        variable = action.variable_name or action.output_key or "result"
        return f"{index}. Execute JavaScript and store result in {variable}"

    def _clean_code_block(self, code: str) -> str:
        """Remove markdown code block wrapper if present."""
        code = code.strip()
        if code.startswith("```python"):
            code = code[9:]
        elif code.startswith("```"):
            code = code[3:]
        code = code.removesuffix("```")
        return code.strip()

    def _extract_code_block(self, code: str) -> str:
        """Extract a JavaScript code block if present."""
        match = re.search(r"```(?:javascript|js)?\s*(.*?)```", code, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return code.strip()

    def _wrap_with_frontmatter(self, name: str, description: str, content: str) -> str:
        """Wrap content with YAML frontmatter."""
        return f"""---
name: {name}
description: {description}
---

{content}
"""

    def _generate_browser_skill_md(
        self,
        name: str,
        description: str,
        actions_md: str,
    ) -> str:
        """Generate SKILL.md content for browser skill."""
        title = name.replace("-", " ").title()
        return f"""---
name: {name}
description: {description}
type: browser
---

# {title}

## Description

{description}

## Recorded Actions

{actions_md}

## Execution

To execute this skill, run the `script.py` file in this directory:

```bash
python script.py
```

The script will:
1. Launch a browser window
2. Execute the recorded actions
3. Extract and return page content as JSON

## When to Use

- When you need to automate this specific browser workflow
- When the user requests this action
"""

    def generate_extraction_js(
        self,
        html: str,
        user_prompt: str = "",
        description: str = "",
    ) -> dict[str, str]:
        """Generate JavaScript to extract data from HTML using an LLM."""
        from deepagents_web.extensions.models import create_model

        prompt = f"""You are an expert at writing browser extraction JavaScript.

{description or "Generate JavaScript that extracts structured data from the provided HTML."}

HTML:
{html[:15000]}

{f"User requirements: {user_prompt}" if user_prompt else ""}

Requirements:
- Return an IIFE that returns a JSON-serializable object
- Extract meaningful text, links, images, tables, and lists when present
- Handle missing elements gracefully
- Avoid external dependencies

Output only JavaScript, no markdown."""

        model = create_model()

        async def _invoke() -> str:
            response = await model.ainvoke([{"role": "user", "content": prompt}])
            return response.content if hasattr(response, "content") else str(response)

        js_response = self._run_coroutine_sync(_invoke())
        js_response = js_response if isinstance(js_response, str) else str(js_response)
        js_code = self._extract_code_block(js_response)
        model_name = getattr(model, "model_name", "") or getattr(model, "model", "")

        return {"javascript": js_code, "used_model": str(model_name)}

    def generate_formfill_js(
        self,
        html: str,
        user_prompt: str = "",
        description: str = "",
    ) -> dict[str, str]:
        """Generate JavaScript to fill form fields using an LLM."""
        from deepagents_web.extensions.models import create_model

        prompt = f"""You are an expert at writing browser form fill JavaScript.

{description or "Generate JavaScript that fills the form with realistic test data."}

HTML:
{html[:15000]}

{f"User requirements: {user_prompt}" if user_prompt else ""}

Requirements:
- Return an IIFE that fills visible form fields
- Trigger input/change events after setting values
- Use realistic placeholder data (names, emails, addresses)
- Return a JSON-serializable summary of filled fields
- Avoid external dependencies

Output only JavaScript, no markdown."""

        model = create_model()

        async def _invoke() -> str:
            response = await model.ainvoke([{"role": "user", "content": prompt}])
            return response.content if hasattr(response, "content") else str(response)

        js_response = self._run_coroutine_sync(_invoke())
        js_response = js_response if isinstance(js_response, str) else str(js_response)
        js_code = self._extract_code_block(js_response)
        model_name = getattr(model, "model_name", "") or getattr(model, "model", "")

        return {"javascript": js_code, "used_model": str(model_name)}

    def ai_extract(self, content: str, prompt: str) -> str:
        """Use LLM to extract information from page content."""
        from deepagents_web.extensions.models import create_model

        full_prompt = f"""Extract information from the following web page content.

User Request: {prompt}

Page Content:
{content}

Respond with ONLY the extracted information, no explanations."""

        model = create_model()

        async def _invoke() -> str:
            response = await model.ainvoke([{"role": "user", "content": full_prompt}])
            return response.content if hasattr(response, "content") else str(response)

        result = self._run_coroutine_sync(_invoke())
        return result if isinstance(result, str) else str(result)

    def ai_generate(self, prompt: str) -> str:
        """Use LLM to generate content for form filling."""
        from deepagents_web.extensions.models import create_model

        full_prompt = f"""Generate content based on the following request.

Request: {prompt}

Respond with ONLY the generated content, no explanations or formatting."""

        model = create_model()

        async def _invoke() -> str:
            response = await model.ainvoke([{"role": "user", "content": full_prompt}])
            return response.content if hasattr(response, "content") else str(response)

        result = self._run_coroutine_sync(_invoke())
        return result if isinstance(result, str) else str(result)
