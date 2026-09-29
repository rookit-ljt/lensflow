# AI Video Studio · 七层架构的代码目录与关键实现

> 对照 `outputs/ai-video-studio-architecture.excalidraw` 的分层图，逐层列出真实代码目录、文件清单和关键实现入口。行号以当前代码为准。

## 总览：层 → 目录 → 规模

| 层 | 目录 | 规模 |
|---|---|---|
| ① 表现层 | `apps/web/` | `studio-workspace.tsx` 1623 行 + `components/studio/` 14 个组件 |
| ② 共享协议层 | `packages/workflow-schema/` | 单文件 `src/index.ts` |
| ③ 应用层 | `apps/api/app/`（main / auth / workflows / schemas…） | `main.py` 2237 行，47 条路由 |
| ④ Agent 子系统 | `apps/api/app/agent_*.py` | 7 个文件，约 3200 行 |
| ⑤ 任务执行层 | `apps/api/app/celery_app.py` + `tasks.py` | 16 + 146 行 |
| ⑥ Provider 适配层 | `apps/api/app/providers/` | 9 个 Provider 实现 |
| ⑦ 数据与外部服务 | `apps/api/app/db_models.py` / `database.py` / `uploads.py` | 18 张表 |

---

## ① 表现层 · `apps/web`（Next.js 15 + React 19）

```
apps/web/
├── app/                          # App Router 页面
│   ├── page.tsx                  # 首页（作品入口）
│   ├── dashboard/page.tsx        # 项目列表页
│   └── projects/[projectId]/page.tsx  # 工作台页（挂载 StudioWorkspace）
├── components/
│   ├── studio-workspace.tsx      # ★ 工作台主容器（1623 行）
│   ├── auth/                     # auth-gate / auth-screen 登录门
│   ├── dashboard/project-dashboard.tsx
│   └── studio/                   # ★ 工作台子组件
│       ├── studio-node.tsx       # React Flow 自定义节点
│       ├── studio-edge.tsx       # 自定义连线
│       ├── chat-agent.tsx        # Chat Agent 面板（885 行）
│       ├── node-composer.tsx     # 节点创作面板（891 行）
│       ├── asset-library.tsx     # 资产库
│       ├── skill-library.tsx     # Skill 库
│       ├── mention-picker.tsx    # @ 引用选择器
│       └── agent-question-dialog.tsx  # Agent 追问对话框
└── lib/
    ├── api.ts                    # ★ 全部后端调用的类型 + api 对象（600 行）
    └── utils.ts
```

**关键实现**

- **画布状态**（`studio-workspace.tsx:221-222`）：`useNodesState<StudioFlowNode>` / `useEdgesState<Edge>`，React Flow 受控模式；节点渲染交给 `studio/studio-node.tsx`，拖线/删除等变更走 `onNodesChange / onEdgesChange`。
- **轮询恢复**（`studio-workspace.tsx:788` 起）：选中任务为 `queued/running` 时每 1.5s 调 `api.getGeneration`，带 10 分钟截止时间兜底（2026-09-14 修复的无限轮询 bug 就在这里）。
- **SSE 订阅**（`chat-agent.tsx:426`）：`new EventSource(api.agentEventStreamUrl(run.id, after), …)`，断线时利用 EventSource 自动重连，从 `after` 事件序号续传；审批卡片/中断选项由 `AgentApproval` / `AgentInterrupt` 事件驱动。
- **API 封装**（`lib/api.ts:418`）：单一 `api` 对象 + 完整 TS 类型（`Generation`、`Workflow`、`CanvasPatchOperation` 等），前端不出现裸 `fetch` 拼接。

---

## ② 共享协议层 · `packages/workflow-schema`

```
packages/workflow-schema/src/index.ts
```

**关键实现**（Zod Schema，前后端共用的画布协议）

- `portDataTypeSchema`（L3）：端口数据类型枚举；
- `workflowNodeSchema`（L12）/ `workflowEdgeSchema`（L20）：节点与连线结构；
- `productWorkflowSchema`（L28）：整张工作流（含 viewport）；
- `NodeDefinition` / `NodePortDefinition`（L44/L51）：节点能力声明（哪些端口可连）。

**注意（2026-09-17 核查）**：这个包**目前没有被实际引用**——`apps/web/package.json` 声明了 `workspace:*` 依赖、`next.config.ts` 配了 `transpilePackages`，但 `apps/web` 源码里零 import；前端实际使用的是自己的本地类型（`lib/api.ts` 的 `Workflow/WorkflowNodeRecord/WorkflowEdgeRecord` + `studio/studio-types.ts` 的 `StudioNodeData`），后端用 `schemas.py`（Pydantic）。即三份类型并存、互不引用，包属于"接线完成但空转"的脚手架：要么让前端改为 `import type { WorkflowNode } from "@ai-video-studio/workflow-schema"`，要么删掉，否则协议变更时它不会报错、只会静默漂移。

---

## ③ 应用层 · `apps/api/app`（FastAPI + SQLAlchemy 2）

```
apps/api/app/
├── main.py            # ★ 47 条路由 + 派发/编排辅助函数（2237 行）
├── auth.py            # 认证
├── workflows.py       # 工作流持久化与版本并发
├── schemas.py         # Pydantic 请求/响应模型（497 行）
├── config.py          # Settings（env 读取）
├── database.py        # engine / Session / Base
├── runtime_settings.py# 运行时可改的 LLM 配置
├── uploads.py         # 上传文件落盘
├── video_frames.py    # 视频末帧提取
└── generation_context.py  # 生成上下文（上游结果引用）
```

**路由清单**（`main.py`，47 条，按 tag 分组）

| 组 | 代表路由 → 处理函数 |
|---|---|
| auth | `POST /api/auth/register` → `register_user`、`POST /api/auth/google` → `login_with_google`、`POST /api/auth/logout` → `logout_user` |
| projects | `GET/POST /api/projects`、`GET /api/projects/{id}/export` → `export_project`（整项目导出） |
| shots/generations | `POST /api/shots/{id}/generations` → `create_generation`、`POST /api/shots/{id}/run` → `run_shot_workflow`、`POST /api/generations/{id}/retry` / `cancel` / `last-frame` / `download` |
| workflow | `GET/PUT /api/shots/{id}/workflow` → `get_workflow` / `save_workflow` |
| agent | 16 条：threads / runs / approval / resume / events / `events/stream`(SSE) |
| assets/uploads | `POST /api/uploads` → `upload_image`、`DELETE /api/assets/{id}` |
| system | `GET /api/providers` → `list_provider_capabilities`、`GET/PUT /api/settings`、`POST /api/feedback` |

**关键实现**

- **所有权隔离**（`main.py:205-267`）：`_owned_project / _owned_shot / _owned_thread / _owned_run / _owned_generation / _owned_asset` 六个守卫函数，任何跨用户访问统一 404——所有路由的第一行都是它们。
- **认证**（`auth.py`）：`hash_password`（scrypt）、`session_token_hash`（库里只存 token 哈希）、`create_auth_session` + `set_auth_cookie`（HttpOnly Cookie）、`require_user`（每请求鉴权）。
- **乐观并发**（`workflows.py`）：`replace_workflow` 校验 `base_revision`，冲突抛 `WorkflowVersionConflict` → API 层转 409；`load_workflow` / `get_or_create_workflow` 负责默认模板（`_default_nodes` / `_default_edges`）。
- **环检测**（`main.py:269` `_workflow_contains_cycle`）：保存工作流时拒绝循环连线。
- **僵尸回收**（`main.py:133` `_fail_interrupted_generations`）：启动时把遗留 queued/running 孤儿任务标记失败（eager 模式下 `uvicorn --reload` 重启会杀掉 in-flight 任务）。
- **任务派发**（`main.py:347` `_enqueue_generation`）：`local_h3` 视频 + eager 模式走 `background_tasks.add_task`（同进程后台任务），其余走 `generate_shot.delay(...)`；`delay` 失败时回写 FAILED 并返回 503。
- **整镜头运行**（`main.py:1887` `run_shot_workflow`）：手工实现 Kahn 拓扑排序（`incoming/outgoing` 邻接表 + ready 队列），只执行 `generator` 节点；有环直接 409。目前仅 eager 模式可用。

---

## ④ Agent 子系统 · `apps/api/app/agent_*.py`（LangGraph-ready）

```
apps/api/app/
├── agent_runtime.py    # ★ AgentRuntime Protocol + SimpleAgentRuntime（896 行）
├── agent_service.py    # ★ 编排：run 执行/审批/中断/恢复（1687 行）
├── agent_canvas.py     # ★ CanvasPatch 编译与应用（495 行）
├── agent_tools.py      # 模型可用工具声明（103 行）
├── agent_questions.py  # 追问/选项规范化（132 行）
├── agent_context.py    # 对话上下文组装（209 行）
└── agent_skills.py     # 7 个内置 Skill 定义（185 行）
```

**关键实现**

- **可替换运行时**（`agent_runtime.py`）：`AgentRuntime`（Protocol，L266）定义 `plan` 契约；`SimpleAgentRuntime`（L276）是当前唯一实现——直接调 `OpenAICompatibleTextProvider`，没引 LangGraph，但 `AgentState`（TypedDict，L218）已按图状态机形态建模，迁移时只需换 Runtime 实现。
- **确认信封**（`agent_runtime.py:30` `parse_confirmation_request`）：模型输出必须包在 `[[AGENT_CONFIRMATION]]…[[/AGENT_CONFIRMATION]]` 里才被解析为画布操作请求；**解析在服务端**，模型自己无法创建真实操作。
- **安全边界**（`agent_canvas.py`）：
  - `ALLOWED_CONFIG_FIELDS` 白名单（L 前 50 行内）：节点 config 只允许白名单字段进入 patch；
  - `compile_canvas_patch`：把模型的操作意图（`create_node / update_node_config / bind_asset`）编译成受限 `CanvasPatch`，带 `base_version` 画布版本校验，冲突抛 `CanvasVersionConflict`；
  - `apply_canvas_patch`：仅在用户**批准后**（`AgentApproval`）于事务内应用。
- **审批与中断**（`agent_service.py`）：
  - `prepare_canvas_approval` → 生成待审批记录；`resolve_agent_approval` → 批准后调 `apply_canvas_patch` + `_enqueue_approved_generations`（`main.py:383`，复用手工生成的同一条派发链路）；
  - 会花钱的动作走 `AgentInterrupt`：`create_node_generation_interrupt` / `create_visual_style_interrupt` / `create_llm_confirmation_interrupt` 等，`resolve_agent_interrupt` → `_resume_selected_node_generation` 在恢复时**重新读配置并校验 Provider**（不信任中断时刻的旧参数）；
  - `execute_agent_run` 是单次运行的主循环：组装上下文 → 调 Runtime → 落 `agent_events`。
- **工具声明**（`agent_tools.py`）：`PlanCanvasArguments` / `AskUserArguments`（Pydantic）+ `plan_canvas_tool` / `ask_user_tool`，作为 OpenAI tool-calling 的 tools 数组传给模型。
- **落库表**：`agent_threads / agent_runs / agent_messages / agent_events / agent_approvals / agent_interrupts` 全量留痕，前端刷新后可完整恢复现场。

---

## ⑤ 任务执行层 · Celery 5

```
apps/api/app/celery_app.py   # Celery 实例（16 行）
apps/api/app/tasks.py        # 唯一任务 generate_shot（146 行）
```

**关键实现**

- **唯一任务**（`tasks.py:9`）：`@celery_app.task(name="ai-video-studio.generate_shot")` → `generate_shot(generation_id)`：读 Generation → 按注册表解析 Provider → `provider.generate(request)` → 产物落盘/建 Asset → 状态回写 `succeeded/failed`（两条路径都会落终态）。
- **双运行模式**（`config.py` + `main.py:347`）：
  - 开发：`CELERY_TASK_ALWAYS_EAGER=true` → 任务在 API 进程内跑（`local_h3` 视频改用 BackgroundTasks，避免阻塞响应）；
  - 生产：`.env` 关掉 eager 后走 RabbitMQ，Worker 用 `pnpm api:worker` 启动。
- **队列**：`docker-compose.yml` 里的 RabbitMQ 4；任务 ID 回写 `generations.celery_task_id`，cancel 接口据此 `AsyncResult.revoke`。

---

## ⑥ Provider 适配层 · `apps/api/app/providers/`

```
providers/
├── base.py                    # ★ 统一协议（Protocol + dataclass）
├── __init__.py                # 9 个 Provider 的注册表（显式 import）
├── mock.py                    # Mock 三件套（文本/图片/视频）
├── openai_compatible.py       # 文本：任意 OpenAI 兼容 API
├── qwen_text.py               # 文本：阿里云百炼千问
├── openai_compatible_image.py # 图片：OpenAI 兼容
├── qwen_image.py              # 图片：千问多模态
├── ark_seedream.py            # 图片：火山方舟 Seedream
├── google_genai_image.py      # 图片：Google Gemini
└── local_h3_video.py          # 视频：本机 MiniMax H3 (127.0.0.1:8787)
```

**关键实现**（`base.py`）

- 三个协议：`TextProvider` / `ImageProvider` / `VideoProvider`，各只有一个方法 `generate(request) -> GenerationResult`；
- 两个数据类：`GenerationRequest`（prompt / model / context 资产 / 参数）、`GenerationResult`（产物路径或 URL + 元数据）；
- 辅助规则：`prompt_with_text_context`（图片生成时可注入上游文本结果）、`ensure_no_image_context`（某些 Provider 不支持图生图时快速失败）。

前端通过 `GET /api/providers`（`main.py:609` `list_provider_capabilities`）读取各 Provider 的**能力状态**（是否配置了 Key），API Key 始终只存在于后端进程。

---

## ⑦ 数据与外部服务

**数据层**

```
apps/api/app/db_models.py   # 18 张表（520 行）
apps/api/app/database.py    # engine/Session（SQLite 开发 / PostgreSQL 17 生产）
```

18 张表：`users, auth_sessions, user_identities, stored_uploads, projects, shots, generations, assets, feedback, workflows, workflow_nodes, workflow_edges, agent_threads, agent_runs, agent_messages, agent_events, agent_approvals, agent_interrupts`。

关系链：`projects → shots → workflows(workflow_nodes/edges) → generations / assets`，Agent 六表挂在 project/thread 下；**全部业务表带 `user_id` 外键**做隔离。

**外部服务**（都在 Provider 层内调用，不在应用层）

- 阿里云百炼（千问文本/图片）、火山方舟（Seedream）、Google Gemini（图片）、本机 `127.0.0.1:8787` MiniMax H3（视频）；另有 Google Identity（`google_identity.py`，Google 登录）。

**资产文件**：本地 `uploads/` 目录（`uploads.py` 落盘 + `read_upload` 静态下发）；`.env.example` 里的对象存储变量代码尚未引用。

---

## 两条容易误解的主线（读代码前先知道）

1. **连线 ≠ DAG 自动调度**：`workflow_edges` 只是声明"该节点生成时引用哪些上游结果"；只有 `run_shot_workflow`（`main.py:1887`）在前端触发时做一次拓扑排序串行执行。单独点某个节点生成时，只取它的直接上游。
2. **生成状态靠轮询，Agent 事件才走 SSE**：`GET /api/generations/{id}` 是前端每 1.5s 拉取的；只有 `GET /api/agent/runs/{id}/events/stream` 是流式。两套通道不要混为一谈。
