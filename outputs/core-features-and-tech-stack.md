# 核心功能与技术栈

> 事实来源：仓库当前可运行代码（`apps/web`、`apps/api`、`packages/workflow-schema`）、`.env.example`、`docker-compose.yml`、`outputs/ai-video-studio-web-architecture.md`。
> 版本号取自各 `package.json` / `pyproject.toml` 的实际约束。

## 一句话定位

面向浏览器的项目制 AI 视频创作平台：用户按「镜头」组织文本、提示词与生成节点，用连线声明依赖，调用云端文本/图片模型和本机视频模型，在画布上直接看结果；右侧 Chat Agent 可以读取画布上下文、提出受限的画布修改计划，但**必须经用户批准才能落地**。

---

## 1. 核心功能清单

| # | 核心功能 | 一句话说明 | 关键落点 |
|---|---|---|---|
| 1 | Product Workflow 画布 | 每个镜头一份独立工作流，节点/连线/位置/视口全量持久化 | `components/studio-workspace.tsx`、`apps/api/app/workflows.py` |
| 2 | 镜头级工作流自动装配 | 新建镜头自动生成 `shot → prompt → generator` 三节点两连线 | `workflows.py` |
| 3 | 整镜头运行 | 按画布拓扑顺序执行已配置的生成节点 | `POST /api/shots/{shot_id}/run` |
| 4 | 多模态生成 + Provider 可插拔 | 文本/图片/视频生成，执行前服务端二次校验 Provider 与密钥 | `apps/api/app/providers/`、`tasks.py` |
| 5 | 连线即生成上下文 | 直接上游节点的最近成功结果自动注入下游 Prompt | `apps/api/app/generation_context.py` |
| 6 | Chat Agent | 感知项目/镜头/选中节点/上下游/最近任务的多轮对话，SSE 增量输出 | `components/studio/chat-agent.tsx`、`agent_runtime.py` |
| 7 | Agent 受限动作 + 人工审批 | 画布修改只出 Plan，编译成白名单 CanvasPatch，批准后才在事务内应用 | `agent_canvas.py`、`agent_service.py` |
| 8 | Agent 受控生成闭环 | 「生成当前节点」先确认可能计费，再次确认才创建 Generation | `agent_tools.py`、`AgentInterrupt` |
| 9 | 项目资产库 | 上传/浏览/搜索/筛选/下载/删除，生成结果自动入库，删除有引用保护 | `components/studio/asset-library.tsx`、`Asset` 模型 |
| 10 | `@` 引用选择器 | 在 Agent 与节点提示词中输入 `@` 引用节点/资产/镜头/生成结果 | `components/studio/mention-picker.tsx` |
| 11 | Agent Skill 库 | 内置 7 个创作方法论 Skill，可搜索/收藏/启用，支持本地自定义 | `apps/api/app/agent_skills.py` |
| 12 | 用户体系与数据隔离 | 本地免登录单用户；可开启邮箱密码/Google 登录，所有资源按用户隔离 | `apps/api/app/auth.py` |
| 13 | 开发态模型设置 | 工作台内改模型/Base URL 并即时生效，Key 不回显不落库 | `routes /api/settings`、`runtime_settings.py` |

---

## 2. 功能 → 技术栈映射

### 2.1 工作流画布与持久化（功能 1–3）

| 能力 | 技术选型 |
|---|---|
| 画布渲染与交互 | `@xyflow/react` 12.8（React Flow），自定义节点/连线组件 |
| 节点状态管理 | React 19 Hooks（`useNodesState/useEdgesState`）；zustand 5 已安装但未接管主状态 |
| 前端协议校验 | zod 4.1（`packages/workflow-schema`） |
| 服务端持久化 | FastAPI + SQLAlchemy 2（`workflows` / `workflow_nodes` / `workflow_edges` 三表） |
| 并发控制 | 单调递增 `revision` + 唯一 `operation_id`：重复请求幂等，过期草稿返回 409 |

### 2.2 生成链路（功能 4–5）

| 能力 | 技术选型 |
|---|---|
| 任务队列 | Celery 5.5；开发默认 `CELERY_TASK_ALWAYS_EAGER=true` 同进程跑，生产走 RabbitMQ 4 + `pnpm api:worker` |
| Provider 抽象 | `providers/base.py` 统一协议 + `tasks.py` 路由（按 kind/provider 分派） |
| 云端调用 | httpx 0.28 直连；Google Gemini 走 `google-genai` 1.62 SDK |
| 文本 Provider | Mock / OpenAI-compatible / 通义千问（`qwen3.7-plus`） |
| 图片 Provider | 千问（`qwen-image-plus`；带 1–3 张参考图时自动切 `qwen-image-2.0-pro` 走多模态编辑）/ 火山方舟 Seedream / Gemini / OpenAI-compatible / Mock |
| 视频 Provider | 本机 MiniMax H3 异步 HTTP 服务（`127.0.0.1:8787`），首尾帧 + 轮询 + 画布内播放 + 末帧入库；Mock 兜底 |
| 结果回传 | 前端定时轮询 Generation 状态（非 WebSocket） |

### 2.3 Chat Agent 与审批边界（功能 6–8、10、11）

| 能力 | 技术选型 |
|---|---|
| Runtime 抽象 | 自定义 `AgentRuntime` Protocol，当前实现 `SimpleAgentRuntime`，可替换为 LangGraph |
| 流式输出 | SSE（`GET /api/agent/runs/{run_id}/events/stream`），支持停止回答与部分内容恢复 |
| 对话持久化 | SQLAlchemy 模型 `agent_threads` / `agent_runs` / `agent_messages` / `agent_events` |
| 工具调用 | OpenAI 兼容 function calling（`AGENT_TOOL_PROTOCOL=auto`），工具为 `ask_user` + `plan_canvas` |
| 审批与中断 | `agent_approvals`（画布补丁）+ `agent_interrupts`（1:N 选择卡片），支持刷新恢复和同 Run Resume |
| 安全边界 | 字段白名单 + `base_revision` 二次校验 + 事务应用；模型无法直接写库 |
| Agent 模型 | 复用千问文本配置（`AGENT_PROVIDER=qwen/openai_compatible/mock`） |
| Skill 注入 | 服务端内置 Catalog（video-director、stable-video-prompt、storyboard-continuity、h3-ref2va-continuity、local-video-producer、script-to-manga、character-turnaround-prompts），作为 Run 上下文注入 |

### 2.4 资产、账号与运维（功能 9、12、13）

| 能力 | 技术选型 |
|---|---|
| 文件上传与本地存储 | FastAPI UploadFile + 本地 `apps/api/uploads/`，DB 记录 `stored_uploads` / `assets` |
| 引用保护 | 删除前检查画布引用，仍被引用的资产拒绝删除 |
| 密码存储 | scrypt（随机盐）+ 会话 Token 仅存 SHA-256 摘要 |
| 会话传递 | HttpOnly Cookie（30 天），可选 `AUTH_REQUIRED=true` 强制登录 |
| 第三方登录 | Google Identity（`google-auth`） |
| 配置管理 | pydantic-settings 2.10，全部集中在根目录 `.env` |

---

## 3. 技术栈总览

| 层 | 技术栈 |
|---|---|
| 前端框架 | Next.js 15.5（App Router）、React 19.1、TypeScript 5.9 |
| 前端 UI | Tailwind CSS 4.3 + tw-animate-css、shadcn 4.16、`@base-ui/react` 1.7、Lucide 图标、CVA / clsx / tailwind-merge |
| 前端画布 | `@xyflow/react` 12.8 |
| 后端框架 | Python ≥ 3.12、FastAPI 0.116+、uvicorn 0.35、pydantic-settings 2.10 |
| ORM / 数据库 | SQLAlchemy 2.0；开发 SQLite，Docker 环境 PostgreSQL 17（psycopg 3.2） |
| 任务 / 消息 | Celery 5.5、RabbitMQ 4（eager 模式可绕过） |
| 模型接入 | httpx 0.28、google-genai 1.62、google-auth 2.40 |
| 共享协议 | `packages/workflow-schema`（zod 4 的 `schemaVersion 1.0` + nodes / edges / viewport） |
| 工程化 | pnpm workspace monorepo（`apps/*`、`packages/*`）、hatchling 构建、tsc --noEmit 全量类型检查 |
| 质量保障 | pytest 8.4 + FastAPI TestClient + httpx MockTransport、Ruff 0.12（line-length 100，target py312） |
| 本地基础设施 | docker compose（postgres / rabbitmq，含 healthcheck） |
| 外部模型服务 | 阿里云百炼 DashScope、火山方舟 Seedream、Google Gemini、本机 MiniMax H3 |

---

## 4. 值得记住的工程约定

1. **密钥只留在后端**：API Key 仅由 FastAPI/Celery 进程读取，不发给浏览器、不写数据库；前端通过 `/api/providers` 只读模型名与配置状态。
2. **Mock 优先**：Mock Provider 只验证编排链路，不产生费用，也不允许展示虚假的视频结果或费用。
3. **连线不是 DAG 调度**：当前连线只声明「生成时引用哪些上游结果」，不做环检测、不做端口类型校验，只有整镜头运行接口在前端侧做了拓扑排序。
4. **Agent 永远不能直写数据库**：所有画布变更都必须经过「Plan → CanvasPatch 白名单 → 用户批准 → 事务应用」。
5. **API 必须用脚本启动**：`pnpm api:dev` / `pnpm api:worker` 固定使用 `apps/api/.venv`，避免误用到 Conda 或系统全局的 `uvicorn`。
6. **开发/生产配置分界**：运行时模型设置仅在 `ENVIRONMENT=development` 且 `RUNTIME_SETTINGS_ENABLED=true` 时开放，生产必须关闭并改用 Secret 注入。

---

## 5. 当前边界（尚未实现，别误读为已有能力）

- 云端视频 Provider、图生视频、音频生成（音频节点仅保留协议兼容）。
- 对象存储：`.env.example` 里有 `OBJECT_STORAGE_*` 变量，但代码中尚未引用，资产仍是本地目录 + 临时 URL。
- Workflow Compiler / 整图 DAG 调度、正式 Workflow 版本与 Execution Snapshot。
- 数据库迁移体系：没有 Alembic，历史库靠 `ensure_auth_columns()` / `ensure_generation_columns()` 这类兼容迁移。
- 权限与计费：无组织、成员角色、额度、账单和审计。
- 正式时间轴与 FFmpeg 合成、字幕、音轨。
- Generation 实时事件（WebSocket）；目前仍是轮询。
