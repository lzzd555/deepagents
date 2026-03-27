# ScienceClaw 架构升级：上下文管理与落盘机制解析

本文档记录了本项目集成 ScienceClaw 核心架构后的上下文管理逻辑。其核心哲学是 **“大脑瞬时重组，灵魂物理持久化” (Stateless Agent, Stateful Soul)**。

---

## 1. 核心流程：上下文生命周期

当前的架构摒弃了长寿命 Agent 实例，改为在每一轮对话中执行 **“即时重组 (Instant Instantiation)”**。

### 第一阶段：收集与注入 (Context Recombination)
当用户发送消息时，系统会启动“重组”程序：
1.  **多源物理扫描**：
    *   `~/.deepagents/{assistant_id}/AGENTS.md`：加载全局通用指令。
    *   `project_root/.deepagents/AGENTS.md`：加载项目基础背景。
    *   `project_root/.deepagents/CONTEXT.md`：**核心知识位面**，加载项目动态进展与习得知识。
2.  **透明化注入**：`MemoryMiddleware` 将上述文件内容通过 `<agent_memory>` 标签注入到大模型的 **System Prompt** 最顶部。
3.  **历史追溯**：从 `AsyncSqliteSaver` 数据库中提取 `thread_id` 对应的对话序列。

### 第二阶段：执行与学习 (Active Learning)
Agent 在处理请求时，会根据 `MemoryMiddleware` 内置的“学习指南”进行实时评估：
*   **显式学习**：用户直接提供的偏好或规范。
*   **隐式学习**：Agent 在执行任务中发现的有效模式或错误纠正。

### 第三阶段：遗产沉淀 (Legacy Capture)
为了确保新知识不随 Agent 的销毁而消失，系统在 **会话关闭 (Session Close)** 时执行以下操作：
*   **触发条件**：用户在 CLI 输入 `exit`/`quit` 或 Web 端的 WebSocket 断开/Session 删除。
*   **总结任务**：重组一个临时的总结 Agent，强制审视全量对话历史。
*   **物理落盘**：将提炼后的结构化知识通过 `write_file` 写入 `.deepagents/CONTEXT.md`。

---

## 2. 核心架构变更

| 模块 | 变更项 | 说明 |
| :--- | :--- | :--- |
| **CLI UI** | `PlanWidget` | 新增独立任务进度面板，通过 `updates` 流实时显示 Todo 状态。 |
| **Backend** | 瞬时实例化 | 移除 `AgentSession` 对 Agent 对象的长持有，改为按需动态创建。 |
| **Config** | `CONTEXT.md` 自动初始化 | 启动对话时若缺失项目级上下文文件，系统会自动创建初始模板。 |
| **Workspace** | `uv` 一体化 | 根目录配置 `pyproject.toml`，整合所有 lib 模块，支持 `uv sync` 一键部署。 |

---

## 3. 机制优势

*   **知识透明化**：`CONTEXT.md` 人机共读，用户可随时干预，AI 习得成果清晰可见。
*   **热切换支持**：支持在对话间隙更换模型参数，每一轮都是全新的、环境对齐的大脑。
*   **高稳健性**：数据库存储原始历史，文件系统存储语义知识，彻底解决了内存泄漏与状态漂移问题。

---

## 4. 维护与开发者指南

- **强制同步**：若发现 Agent 认知有误，直接修改项目根目录的 `.deepagents/CONTEXT.md` 即可。
- **环境部署**：在根目录运行 `uv sync` 即可完成全模块（CLI, Web, ACP 等）的依赖安装。
