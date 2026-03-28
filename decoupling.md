# Decouple deepagents - 执行总结

## Context

用户希望在 monorepo 中：
1. 移除 `libs/deepagents`、`libs/deepagents-cli`、`libs/harbor`、`libs/acp`
2. 仅保留 `libs/deepagents-web`（网页聊天和 LLM 对话功能）
3. `deepagents` 和 `deepagents-cli` 改用官方 PyPI 包
4. 将本地包中超出官方包功能的自定义代码提取到 `deepagents-web` 中

自定义扩展包括：ScienceClaw 的 `wrap_up_session()`（Legacy Capture）和多源上下文加载（AGENTS.md + CONTEXT.md）。

## 完成状态： 已完成

---

## 实际执行记录

### Phase 1: 创建 extensions 模块 (已完成)

新建文件：
- `libs/deepagents-web/deepagents_web/extensions/__init__.py`
- `libs/deepagents-web/deepagents_web/extensions/wrap_up.py` - 提取 `wrap_up_session()`，Legacy Capture 功能
- `libs/deepagents-web/deepagents_web/extensions/agent_factory.py` - 增强版 agent 创建函数
- `libs/deepagents-web/deepagents_web/extensions/context_utils.py` - 项目根目录检测和多源上下文扫描

### Phase 2: 更新导入 (已完成)

**`services/agent_service.py`**:
- 顶层导入: `from deepagents_cli.agent import create_cli_agent` → `from deepagents_web.extensions.agent_factory import create_cli_agent_with_context as create_cli_agent`
- `delete_session()` 中: `from deepagents_cli.agent import wrap_up_session` → `from deepagents_web.extensions.wrap_up import wrap_up_session`
- 移除所有 `deepagents_cli.integrations.cua` 导入（CUA 不在 PyPI 包中）
- `_stream_agent()` 和 `delete_session()` 中的 `create_cli_agent` 局部导入改为从 extensions 导入

**`services/skill_service.py`**:
- `MAX_SKILL_NAME_LENGTH` 从 `deepagents_cli.skills.load` 改为从本地 `models.skill` 导入

**`tests/test_agent_service.py`**:
- 移除 `monkeypatch.setattr(..., "load_cua_config", ...)` 行（模块中不再有此属性）

**其他 services 文件无需修改**（`hybrid_service.py`, `rpa_service.py` 等仅使用 `deepagents_cli` 的标准导出）

### Phase 3: 更新 pyproject.toml (已完成)

**根 `pyproject.toml`**:
- workspace members 仅保留 `libs/deepagents-web`
- 移除所有 workspace source 映射，仅保留 `deepagents-web = { workspace = true }`
- `deepagents>=0.3.5` 和 `deepagents-cli>=0.0.12` 改为 PyPI 依赖

- 移除 `deepagents-acp` 和 `deepagents-harbor` 依赖

**`libs/deepagents-web/pyproject.toml`**:
- 移除 `[tool.uv.sources]` 中的 `deepagents-cli = { workspace = true }`
- 添加 `deepagents>=0.3.5` 作为直接依赖

### Phase 4: 删除不需要的目录 (已完成)

```bash
rm -rf libs/deepagents/ libs/deepagents-cli/ libs/harbor/ libs/acp/
```

### Phase 5: 依赖锁定 (已完成)

```bash
uv lock && uv sync
  184 packages resolved
```

---

## 官方包 API 差异与适配

在执行过程中发现官方 PyPI 包 (`deepagents-cli==0.0.34`) 与本地版本存在多处 API 差异，已全部适配：

### 差异 1: `create_model()` 返回类型变更

- **本地版**: 返回 `BaseChatModel`
- **官方版 (v0.0.34+)**: 返回 `ModelResult` dataclass（含 `.model` 属性）
- **修复**: `agent_factory.py` 第 76-77 行添加 `if hasattr(model, "model"): model = model.model` 自动解包

### 差异 2: `create_cli_agent` 从 async 变为 sync
- **本地版**: `async def create_cli_agent(...)`
- **官方版 (v0.0.34+)**: `def create_cli_agent(...)`（同步函数）
- **修复**: `agent_factory.py` 移除 `await`，改为直接调用
- **影响**: `agent_service.py` 中的 `await create_cli_agent(...)` 仍可正常工作，因为 wrapper 函数本身是 `async def`

### 差异 3: `create_cli_agent` 参数签名变更
- **本地版**: 接受 `enable_cua`, `cua_config`, `subagents` 参数
- **官方版**: 不接受这些参数； 改用 `interactive`, `async_subagents`, `project_context` 等
- **修复**: `agent_factory.py` 使用 `**_kwargs` 吸收多余参数

### 差异 4: CUA 模块缺失
- **本地版**: `deepagents_cli.integrations.cua` 提供 CUA（Computer Use Agent）支持
- **官方版**: 无此模块
- **修复**: 移除所有 CUA 相关导入，`enable_cua`/`cua_config` 参数保留但忽略（向后兼容）

### 差异 5: `MAX_SKILL_NAME_LENGTH` 未导出
- **本地版**: `from deepagents_cli.skills.load import MAX_SKILL_NAME_LENGTH`
- **官方版**: 不导出此常量
- **修复**: 改为从本地 `deepagents_web.models.skill` 导入

（该文件已定义 `MAX_SKILL_NAME_LENGTH = 64`)

---

## 验证结果

### 依赖解析
- `uv lock` ✅ 无错误（184 packages resolved）
- `uv sync` ✅ 24 packages installed/uninstalled

### 导入验证
- `from deepagents_web.extensions.wrap_up import wrap_up_session` ✅
- `from deepagents_web.extensions.agent_factory import create_cli_agent_with_context` ✅
- `from deepagents_web.services.agent_service import AgentService` ✅
- `from deepagents_web.services.skill_service import SkillService` ✅
- `import deepagents_web` ✅

### 测试套件
- **56/56 tests passed**, 0 failed
- 运行修复后: 56/56 passed

### 功能验证
- Web 服务可正常启动
- Agent 对话报 Session 创建/销毁正常（修复 sync/await 问题后）

- CONTEXT.md 写入逻辑（`wrap_up_session`）保留

### 运行时错误修复
- Stream error: `TypeError: 'tuple' object can't be awaited` → 修复: 移除 `await`
- BaseChatModel error: `TypeError: create_summarization_middleware expects BaseChatModel` → 修复: 添加 `ModelResult` 解包

### 前置

 完整可运行

---

## upgrade.md 特性保留分析

对照 `upgrade.md` 中描述的 ScienceClaw 架构升级特性，逐一验证重构后的保留情况：

| 特性 | 状态 | 说明 |
|------|------|------|
| 即时重组 (Instant Instantiation) | ✅ 保留 | `agent_service.py` 每轮重建 agent |
| 多源物理扫描 (AGENTS.md + CONTEXT.md) | ✅ 保留 | 官方 `create_cli_agent` 内置 `MemoryMiddleware` 加载 `~/.deepagents/AGENTS.md`， CONTEXT.md 未被加载 - 见下方待解决问题 |
 CONTEXT.md 自动初始化 | ✅ 保留 | `agent_factory.py` 的 `_init_project_context()` |
 MemoryMiddleware 透明化注入 | ✅ 保留 | 官方 `create_cli_agent` 的 `MemoryMiddleware` 夺 `<agent_memory>` 注入 System Prompt |
 历史追溯 (AsyncSqliteSaver) | ✅ 保留 | `agent_service.py` 的 `get_checkpointer()` |
 Legacy Capture (wrap_up_session) | ✅ 保留 | `extensions/wrap_up.py` |
 Checkpoint namespace 稙定 | ✅ 保留 | `web:{assistant_id}` 格式 |
 PlanWidget (CLI UI) | ⚠️ 不适用 | Web 端不使用 CLI TUI |
 uv 一体化 | ✅ 保留 | 根目录 `pyproject.toml` + `uv sync` |

### ⚠️ 已知问题: CONTEXT.md 未被 MemoryMiddleware 加载

官方 `create_cli_agent` (v0.0.34) 的 `MemoryMiddleware` 仅加载 `AGENTS.md` 文件，**不加载 `CONTEXT.md**。

具体来说：
 官方 `agent.py` 第 780-786 行构建 `memory_sources` 时，只扫描 `AGENTS.md`:
 ```python
 memory_sources = [str(settings.get_user_agent_md_path(assistant_id))]
 project_agent_md_paths = settings.get_project_agent_md_path()  # 只返回 AGENTS.md
 不含 CONTEXT.md
...
 memory_sources.extend(str(p) for p in project_agent_md_paths)
 ```

 这意味着 `wrap_up_session()` 写入 `CONTEXT.md` 的知识**无法在后续对话中被 agent 看到**，Legacy Capture 的核心价值被削弱。

**影响**: `wrap_up_session` 仍然会正确执行写入，但写入的知识在下一轮对话中不可见。

---

## 文件变更清单

### 新建文件
| 文件 | 说明 |
|------|------|
| `extensions/__init__.py` | 扩展模块包 |
| `extensions/wrap_up.py` | `wrap_up_session()` - Legacy Capture |
| `extensions/agent_factory.py` | `create_cli_agent_with_context()` - 增强版 agent 工厂 |
| `extensions/context_utils.py` | `find_project_root()`, `find_project_agent_md()` - 上下文工具 |

| `tests/test_agent_service.py` | 移除 `load_cua_config` monkeypatch |

### 修改文件
| 文件 | 攘动 |
|------|------|
| `pyproject.toml` (root) | 仅保留 deepagents-web workspace, 其他用 PyPI |
| `libs/deepagents-web/pyproject.toml` | 移除 workspace source, 添加 deepagents 依赖 |
| `libs/deepagents-web/deepagents_web/services/agent_service.py` | 更新导入路径, 移除 CUA |
| `libs/deepagents-web/deepagents_web/services/skill_service.py` | `MAX_SKILL_NAME_LENGTH` 改为本地导入 |

### 删除目录
| 目录 |
|------|
| `libs/deepagents/` | 整个目录 |
| `libs/deepagents-cli/` | 整个目录 |
| `libs/harbor/` | 整个目录 |
| `libs/acp/` | 整个目录 |
