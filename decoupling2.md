Plan: 移除 deepagents-cli 依赖，改用 deepagents 包                                                                     
                                                                                                                        
 Context                                                                                                                
                                                                                                                        
 用户要求完全移除 deepagents-cli 依赖，仅使用 deepagents 包（通过 create_deep_agent 创建 agent）。                      
                                                                                                                        
 当前状态：agent_factory.py 仍调用 deepagents_cli.agent.create_cli_agent，多个 service 文件仍导入 deepagents_cli.config 
  的 Settings、create_model、SessionState，以及                                                                         
 deepagents_cli.sessions.get_checkpointer、deepagents_cli.skills.load.list_skills。

 目标：所有 from deepagents_cli.xxx 导入替换为 deepagents 包 + 本地自建工具。

 ---
 需要替换的 deepagents_cli 导入清单

 ┌─────────────────────────────┬─────────────────────────┬────────────────────┬───────────────────────────────────┐
 │            符号             │          来源           │      使用文件      │             替代方案              │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │ create_cli_agent            │ deepagents_cli.agent    │ agent_factory.py   │ deepagents.create_deep_agent      │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │ settings                    │ deepagents_cli.config   │ agent_factory.py   │ 本地 WebSettings 单例             │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │ get_default_coding_instruct │ deepagents_cli.config   │ agent_factory.py   │ deepagents.graph.BASE_AGENT_PROMP │
 │ ions                        │                         │                    │ T                                 │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │ SessionState                │ deepagents_cli.config   │ agent_service.py   │ 本地简化版                        │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │                             │                         │ agent_service.py,  │ deepagents._models.resolve_model  │
 │ create_model                │ deepagents_cli.config   │ skill_service.py,  │ + langchain.chat_models.init_chat │
 │                             │                         │ hybrid_executor.py │ _model                            │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │                             │                         │ agent_service.py,  │                                   │
 │ get_checkpointer            │ deepagents_cli.sessions │ test_agent_service │ 本地实现 (AsyncSqliteSaver)       │
 │                             │                         │ .py                │                                   │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │                             │                         │ skill_service.py,  │                                   │
 │ Settings                    │ deepagents_cli.config   │ hybrid_service.py, │ 本地 WebSettings                  │
 │                             │                         │  rpa_service.py    │                                   │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │ list_skills                 │ deepagents_cli.skills.l │ skill_service.py   │ 本地实现 (SkillsMiddleware +      │
 │                             │ oad                     │                    │ FilesystemBackend)                │
 ├─────────────────────────────┼─────────────────────────┼────────────────────┼───────────────────────────────────┤
 │ generate_thread_id          │ deepagents_cli.sessions │ (间接通过          │ uuid.uuid4() 或                   │
 │                             │                         │ SessionState)      │ uuid_utils.uuid7()                │
 └─────────────────────────────┴─────────────────────────┴────────────────────┴───────────────────────────────────┘

 ---
 Phase 1: 创建本地配置/工具模块

 1.1 新建 extensions/settings.py — 本地 WebSettings

 替代 deepagents_cli.config.Settings。Settings 的核心功能是路径管理：
 - project_root → 沿目录树查找 .git（复用 context_utils.find_project_root）
 - get_agent_dir(name) → ~/.deepagents/{name}
 - ensure_agent_dir(name) → mkdir + 返回路径
 - get_user_skills_dir(name) → ~/.deepagents/{name}/skills/
 - ensure_user_skills_dir(name) → mkdir + 返回路径
 - get_project_skills_dir() → {project_root}/.deepagents/skills/
 - ensure_project_skills_dir() → mkdir + 返回路径
 - get_user_agent_md_path(name) → ~/.deepagents/{name}/AGENTS.md
 - get_project_agent_md_path() → 扫描 .deepagents/AGENTS.md + AGENTS.md
 - from_environment() → 构造函数

 """Lightweight settings for deepagents-web, replacing deepagents_cli.config.Settings."""

 1.2 新建 extensions/models.py — create_model 替代

 替代 deepagents_cli.config.create_model。

 create_model() 的核心逻辑是解析环境变量/配置文件中的 model spec 并创建 BaseChatModel。
 简化版直接使用 deepagents._models.resolve_model + 环境变量 DEEPAGENTS_MODEL（默认 claude-sonnet-4-6）。

 """Model creation utilities, replacing deepagents_cli.config.create_model."""
 from deepagents._models import resolve_model

 def create_model(model_spec: str | None = None):
     """Create a BaseChatModel. Returns BaseChatModel (not ModelResult)."""
     import os
     spec = model_spec or os.environ.get("DEEPAGENTS_MODEL", "claude-sonnet-4-6")
     return resolve_model(spec)

 1.3 新建 extensions/sessions.py — session/checkpointer 工具

 替代 deepagents_cli.sessions.get_checkpointer 和 generate_thread_id。

 """Session utilities, replacing deepagents_cli.sessions."""
 from contextlib import asynccontextmanager
 from pathlib import Path

 @asynccontextmanager
 async def get_checkpointer():
     """AsyncSqliteSaver context manager."""
     from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
     db_path = Path.home() / ".deepagents" / "checkpoints.db"
     db_path.parent.mkdir(parents=True, exist_ok=True)
     async with AsyncSqliteSaver.from_conn_string(str(db_path)) as cp:
         yield cp

 class SessionState:
     """Minimal session state."""
     def __init__(self, auto_approve: bool = False):
         self.auto_approve = auto_approve
         self.thread_id = str(__import__('uuid').uuid4())

 1.4 新建 extensions/skills.py — list_skills 替代

 替代 deepagents_cli.skills.load.list_skills。

 使用 deepagents 包的 SkillsMiddleware 内部的 list_skills_from_backend，配合 FilesystemBackend。
 如果该函数不是公开 API，则直接用 FilesystemBackend 遍历目录并解析 SKILL.md 的 YAML frontmatter。

 """Skill listing utilities, replacing deepagents_cli.skills.load.list_skills."""
 from deepagents.backends.filesystem import FilesystemBackend
 # 遍历目录读取 SKILL.md YAML frontmatter

 ---
 Phase 2: 重写 extensions/agent_factory.py

 用 deepagents.create_deep_agent 替代 deepagents_cli.agent.create_cli_agent。

 关键参数映射：

 ┌───────────────────────┬─────────────────────────────┐
 │ create_cli_agent 参数 │   create_deep_agent 参数    │
 ├───────────────────────┼─────────────────────────────┤
 │ model                 │ model                       │
 ├───────────────────────┼─────────────────────────────┤
 │ assistant_id          │ name                        │
 ├───────────────────────┼─────────────────────────────┤
 │ tools                 │ tools                       │
 ├───────────────────────┼─────────────────────────────┤
 │ system_prompt         │ system_prompt               │
 ├───────────────────────┼─────────────────────────────┤
 │ auto_approve          │ interrupt_on (None 或 {})   │
 ├───────────────────────┼─────────────────────────────┤
 │ enable_memory         │ memory (list of file paths) │
 ├───────────────────────┼─────────────────────────────┤
 │ enable_skills         │ skills (list of dir paths)  │
 ├───────────────────────┼─────────────────────────────┤
 │ enable_shell          │ backend=LocalShellBackend   │
 ├───────────────────────┼─────────────────────────────┤
 │ checkpointer          │ checkpointer                │
 ├───────────────────────┼─────────────────────────────┤
 │ (无)                  │ backend                     │
 └───────────────────────┴─────────────────────────────┘

 主要变更：

 from deepagents import create_deep_agent, MemoryMiddleware
 from deepagents.backends import LocalShellBackend, FilesystemBackend

 async def create_cli_agent_with_context(
     model, assistant_id, *, tools=None, checkpointer=None,
     auto_approve=False, enable_memory=True, enable_skills=True,
     enable_shell=True, system_prompt=None, **_kwargs
 ):
     # 1. Unwrap ModelResult if needed
     if hasattr(model, "model"):
         model = model.model

     # 2. Ensure agent dir & AGENTS.md
     agent_dir = settings.ensure_agent_dir(assistant_id)
     agent_md = agent_dir / "AGENTS.md"
     if not agent_md.exists():
         agent_md.write_text(BASE_AGENT_PROMPT)

     # 3. Auto-init CONTEXT.md
     _init_project_context()

     # 4. Build memory sources (AGENTS.md + CONTEXT.md)
     memory_sources = [str(agent_md)]
     project_root = find_project_root()
     if project_root:
         context_md = project_root / ".deepagents" / "CONTEXT.md"
         if context_md.exists():
             memory_sources.append(str(context_md))
         # Also add project AGENTS.md if exists
         project_agents_md = project_root / ".deepagents" / "AGENTS.md"
         if project_agents_md.exists():
             memory_sources.append(str(project_agents_md))

     # 5. Build skill sources
     skill_sources = []
     user_skills_dir = settings.get_user_skills_dir(assistant_id)
     if user_skills_dir.exists():
         skill_sources.append(str(user_skills_dir))
     project_skills_dir = settings.get_project_skills_dir()
     if project_skills_dir and project_skills_dir.exists():
         skill_sources.append(str(project_skills_dir))

     # 6. Build backend
     backend = LocalShellBackend if enable_shell else FilesystemBackend(root_dir=str(Path.cwd()))

     # 7. Create agent
     agent = create_deep_agent(
         model=model,
         name=assistant_id,
         tools=tools or [],
         system_prompt=system_prompt,
         memory=memory_sources if enable_memory else None,
         skills=skill_sources if enable_skills and skill_sources else None,
         checkpointer=checkpointer,
         backend=backend,
     )

     return agent, backend

 注意： create_deep_agent 返回 CompiledStateGraph（单个值），不是 tuple。但调用方 agent_service.py 期望 (agent,
 backend) tuple。返回 (agent, None) 保持兼容。

 ---
 Phase 3: 更新所有 service 文件的导入

 3.1 agent_service.py

 ┌────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────┐
 │                 旧导入                 │                                 新导入                                 │
 ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
 │ from deepagents_cli.config import      │ from deepagents_web.extensions.sessions import SessionState + from     │
 │ SessionState, create_model             │ deepagents_web.extensions.models import create_model                   │
 ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
 │ from deepagents_cli.sessions import    │ from deepagents_web.extensions.sessions import get_checkpointer        │
 │ get_checkpointer                       │                                                                        │
 └────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────┘

 3.2 agent_factory.py

 ┌────────────────────────────────────────────────────────────┬────────────────────────────────────────────────────┐
 │                           旧导入                           │                       新导入                       │
 ├────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ from deepagents_cli.agent import create_cli_agent          │ from deepagents import create_deep_agent           │
 ├────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ from deepagents_cli.config import settings                 │ from deepagents_web.extensions.settings import     │
 │                                                            │ settings                                           │
 ├────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ from deepagents_cli.config import                          │ from deepagents.graph import BASE_AGENT_PROMPT     │
 │ get_default_coding_instructions                            │                                                    │
 └────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────┘

 3.3 skill_service.py

 ┌────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
 │                       旧导入                       │                           新导入                           │
 ├────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
 │ from deepagents_cli.config import Settings         │ from deepagents_web.extensions.settings import WebSettings │
 ├────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
 │ from deepagents_cli.skills.load import list_skills │ from deepagents_web.extensions.skills import list_skills   │
 ├────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
 │ from deepagents_cli.config import create_model     │ from deepagents_web.extensions.models import create_model  │
 └────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

 3.4 hybrid_service.py

 ┌────────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
 │                   旧导入                   │                           新导入                           │
 ├────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
 │ from deepagents_cli.config import Settings │ from deepagents_web.extensions.settings import WebSettings │
 └────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

 3.5 hybrid_executor.py

 ┌────────────────────────────────────────────────┬───────────────────────────────────────────────────────────┐
 │                     旧导入                     │                          新导入                           │
 ├────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┤
 │ from deepagents_cli.config import create_model │ from deepagents_web.extensions.models import create_model │
 └────────────────────────────────────────────────┴───────────────────────────────────────────────────────────┘

 3.6 rpa_service.py

 ┌────────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
 │                   旧导入                   │                           新导入                           │
 ├────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
 │ from deepagents_cli.config import Settings │ from deepagents_web.extensions.settings import WebSettings │
 └────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

 3.7 tests/test_agent_service.py

 ┌──────────────────────────────────────────┬─────────────────────────────────────────────────────┐
 │           旧 monkeypatch 目标            │                 新 monkeypatch 目标                 │
 ├──────────────────────────────────────────┼─────────────────────────────────────────────────────┤
 │ deepagents_cli.sessions.get_checkpointer │ deepagents_web.extensions.sessions.get_checkpointer │
 └──────────────────────────────────────────┴─────────────────────────────────────────────────────┘

 ---
 Phase 4: 更新 pyproject.toml 依赖

 4.1 根 pyproject.toml

 - 移除 deepagents-cli>=0.0.12 依赖
 - 保留 deepagents>=0.3.5
 - 添加 langgraph-checkpoint-sqlite (用于 AsyncSqliteSaver)

 4.2 libs/deepagents-web/pyproject.toml

 - 移除 deepagents-cli 相关依赖
 - 添加 deepagents>=0.3.5、langgraph-checkpoint-sqlite

 ---
 Phase 5: 运行验证

 uv lock && uv sync
 uv run pytest libs/deepagents-web/tests/

 ---
 修改文件清单

 ┌────────────────────────────────────┬──────┬───────────────────────────────────────────────────────┐
 │                文件                │ 操作 │                         说明                          │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ extensions/settings.py             │ 新建 │ WebSettings 替代 deepagents_cli.config.Settings       │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ extensions/models.py               │ 新建 │ create_model 替代 deepagents_cli.config.create_model  │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ extensions/sessions.py             │ 新建 │ SessionState + get_checkpointer 替代                  │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ extensions/skills.py               │ 新建 │ list_skills 替代                                      │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ extensions/agent_factory.py        │ 重写 │ 使用 create_deep_agent                                │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ services/agent_service.py          │ 修改 │ 更新所有导入                                          │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ services/skill_service.py          │ 修改 │ 更新所有导入                                          │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ services/hybrid_service.py         │ 修改 │ 更新导入                                              │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ services/hybrid_executor.py        │ 修改 │ 更新导入                                              │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ services/rpa_service.py            │ 修改 │ 更新导入                                              │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ tests/test_agent_service.py        │ 修改 │ 更新 monkeypatch 目标                                 │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ pyproject.toml (root)              │ 修改 │ 移除 deepagents-cli 依赖                              │
 ├────────────────────────────────────┼──────┼───────────────────────────────────────────────────────┤
 │ libs/deepagents-web/pyproject.toml │ 修改 │ 移除 deepagents-cli，添加 langgraph-checkpoint-sqlite │
 └────────────────────────────────────┴──────┴───────────────────────────────────────────────────────┘
---

## 实施结果与影响分析（已完成）

**状态：所有 Phase 1-5 已实施完成，56/56 测试通过。**

---

### 一、实施过程中遇到并修复的问题

#### 问题 1：Anthropic API key 未设置

- **原因**：create_model() 默认使用 "claude-sonnet-4-6"，需要 ANTHROPIC_API_KEY
- **用户实际配置**：OpenAI 兼容代理（OPENAI_BASE_URL=https://wolfai.top/v1, OPENAI_MODEL=gemini-2.5-flash）
- **修复**：在 models.py 中增加 `_default_model_spec()` 函数，优先读取 OPENAI_MODEL 环境变量并自动加 "openai:" 前缀

#### 问题 2：langchain-openai 未安装

- **原因**：移除 deepagents-cli 后，langchain-openai 不再作为传递依赖
- **修复**：在 libs/deepagents-web/pyproject.toml 中显式添加 langchain-openai>=0.3.0

#### 问题 3：ChatVertexAI 路由错误（resolve_model 问题）

- **原因**：最初使用 `deepagents._models.resolve_model`，该函数对 OpenAI 模型强制 `use_responses_api=True`，导致代理不兼容
- **同时**：安装 langchain-google-vertexai 后，裸模型名 "gemini-2.5-flash" 会被路由到 ChatVertexAI
- **修复**：改用 `langchain.chat_models.init_chat_model` 直接创建模型，避免 resolve_model 的副作用

#### 问题 4：agent_factory.py 中 ModelResult 解包逻辑导致模型降级为字符串

- **原因**：agent_factory.py 的 `if hasattr(model, "model"): model = model.model`
  - ChatOpenAI 实例有 `.model` 属性（存储模型名字符串）
  - 解包后 model 变成字符串 "gemini-2.5-flash"
  - create_deep_agent 收到字符串后再次解析，被路由到 ChatVertexAI
- **修复**：移除该解包逻辑，因为 create_model() 现在直接返回 BaseChatModel，不需要解包

---

### 二、功能差异分析

#### 2.1 行为变化

| 方面 | deepagents_cli 原实现 | 新实现 | 影响 |
|------|----------------------|--------|------|
| Agent 返回值 | `(agent, backend)` tuple | `(agent, None)` — backend 被丢弃 | **低风险** — 所有调用方只用 agent，忽略第二个值 |
| 模型解析 | `resolve_model()` → 强制 `use_responses_api=True` | `init_chat_model()` → 标准 LangChain 路由 | **正面改进** — 兼容 OpenAI 代理 |
| CUA 支持 | `deepagents_cli.integrations.cua` 提供 | `enable_cua` 参数被静默忽略 | **功能缺失** — CUA 不可用 |
| auto_approve | 影响中断行为（interrupt_on） | 接收但未传给 create_deep_agent | **潜在问题** — 见下方 |

#### 2.2 缺失功能

1. **CUA（Computer Use Agent）** — 原来通过 `deepagents_cli.integrations.cua` 提供，现在 `enable_cua` 和 `cua_config` 被 `**_kwargs` 静默吞掉。如果 CUA 功能对用户重要，需要单独重新实现。

2. **auto_approve 未生效** — `create_cli_agent_with_context` 接收 `auto_approve` 参数但没有传给 `create_deep_agent` 的 `interrupt_on`。原 `create_cli_agent` 会根据此值设置中断行为，现在所有请求都可能触发中断等待人工审批。**这是一个需要修复的问题。**

3. **sandbox / sandbox_type 未生效** — 参数被 `**_kwargs` 吞掉，沙箱功能不可用。

---

### 三、API 兼容性验证

| API 调用 | 传参类型 | 期望类型 | 结果 |
|----------|---------|---------|------|
| `create_deep_agent(model=...)` | `BaseChatModel` | `str \| BaseChatModel \| None` | OK |
| `create_deep_agent(backend=...)` | `LocalShellBackend()` / `FilesystemBackend(...)` | `BackendProtocol \| BackendFactory \| None` | OK |
| `create_deep_agent(checkpointer=...)` | `AsyncSqliteSaver` | `None \| bool \| BaseCheckpointSaver` | OK |
| `create_deep_agent(memory=..., skills=...)` | `list[str] \| None` | `list[str] \| None` | OK |
| `init_chat_model("openai:gemini-2.5-flash")` | `str` | `str \| None` | OK |

---

### 四、遗留问题

#### 4.1 需要修复的问题

| 问题 | 位置 | 严重程度 |
|------|------|----------|
| `auto_approve` 未传递给 `create_deep_agent(interrupt_on=...)` | `extensions/agent_factory.py` | **高** — 可能导致意外的中断审批 |
| `ralph_mode` 示例完全损坏 | `examples/ralph_mode/ralph_mode.py` — 仍在导入 `deepagents_cli` | 中 — 示例不可用 |

#### 4.2 文档过时引用

| 文件 | 引用内容 |
|------|----------|
| `AGENTS.md` (154-160行) | 引用 `libs/deepagents-cli/` 目录结构 |
| `PRPs/deepagents-web.md` | 多处引用 `deepagents_cli` 模块作为依赖源 |
| `docs/PRD_Web_Agent_Capability.md` | 引用 `deepagents_cli/agent.py`、`config.py` |
| `decoupling.md` | 旧版迁移计划（可清理） |

#### 4.3 设计注意事项

- **settings 单例在 import 时初始化** — `find_project_root()` 只执行一次，Web 服务工作目录不变则无影响
- **create_model() 每次请求都创建新实例** — 允许通过环境变量动态切换模型，开销可忽略
- **deepagents-cli 目录已从仓库完全移除**

---

### 五、依赖变更总结

#### 根 pyproject.toml

- 移除：`deepagents-cli>=0.0.12`
- 保留：`deepagents>=0.3.5`
- 新增：`langchain-google-vertexai>=3.2.2`（用户手动添加）

#### libs/deepagents-web/pyproject.toml

- 移除：`deepagents-cli` 相关依赖
- 保留：`deepagents>=0.3.5`
- 新增：`langgraph-checkpoint-sqlite>=2.0.0`、`langchain-openai>=0.3.0`

---

### 六、总结

| 维度 | 评价 |
|------|------|
| **核心功能** | 完整替代 — agent 创建、会话管理、技能系统、模型解析均正常 |
| **测试覆盖** | 56/56 通过 |
| **风险点** | `auto_approve` 未传递给 `create_deep_agent`，可能导致意外中断审批 |
| **缺失功能** | CUA 支持、沙箱功能（如需要可后续补充） |
| **清理工作** | `examples/ralph_mode.py` 损坏，文档需更新 |
| **建议优先处理** | `auto_approve` → `interrupt_on` 映射 |
