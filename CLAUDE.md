# CLAUDE.md

## 项目概述

AI Video Studio Web Platform —— 面向浏览器的项目制 AI 视频创作平台（MVP）。不依赖 ComfyUI 核心链路，使用 FastAPI + Celery/RabbitMQ + 云模型 Provider。

架构基线文档：`outputs/ai-video-studio-web-architecture.md`

## 仓库结构

```text
apps/web                  Next.js 15 + React 19 创作工作台（App Router）
apps/api                  FastAPI 业务服务（Python >=3.12）+ Celery 任务
packages/workflow-schema  前后端共享工作流协议（TypeScript）
outputs/                  架构设计文档
```

pnpm monorepo（workspace：`apps/*`、`packages/*`）。前端画布使用 `@xyflow/react`，状态用 zustand，UI 用 shadcn/Base UI + Tailwind v4。

## 常用命令

```bash
# 基础设施（Postgres / RabbitMQ）
docker compose up -d postgres rabbitmq

# 前端
pnpm install
pnpm dev            # Web: http://localhost:3000
pnpm build          # 需先构建 workflow-schema（脚本已包含）
pnpm typecheck      # 全 workspace tsc --noEmit

# API（必须用这些脚本；固定使用 apps/api/.venv，勿用 Conda/系统 uvicorn）
pnpm api:setup      # 创建 venv 并 pip install -e 'apps/api[dev]'
pnpm api:dev        # uvicorn, http://localhost:8000 （文档 /docs）
pnpm api:worker     # 独立 Celery worker（可选）

# API 测试与 lint（在 apps/api 下，用 .venv）
cd apps/api && .venv/bin/python -m pytest
cd apps/api && .venv/bin/python -m ruff check .
```

## 关键约定

- **环境变量**：全部配置在根目录 `.env`（模板见 `.env.example`）。API Key 只由 FastAPI/Celery 后端读取，绝不发给浏览器或写入数据库；前端只通过 `/api/providers` 读取配置状态。修改 Provider 配置后需重启 API 和 Worker。
- **数据库**：本地开发默认 SQLite（`ai-video-studio.db`），部署可切 PostgreSQL（`DATABASE_URL`）。所有项目/镜头/工作流/生成记录/Agent 对话/上传素材按用户隔离。
- **任务执行**：开发默认 `CELERY_TASK_ALWAYS_EAGER=true`，无需 RabbitMQ。切独立 Worker 时设为 false 并运行 `pnpm api:worker`。
- **工作流并发控制**：保存携带单调递增 `revision` 与 `operation_id`，支持乐观并发；过期草稿返回 409，重复请求幂等。Agent CanvasPatch 同样带 `base_revision`。
- **Agent 审批模式**：Chat Agent 的画布修改只生成受限 CanvasPatch 预览，用户批准后才应用；不会自动启动模型生成。
- **Mock 优先**：Mock Provider 只验证编排，不产生费用；不要展示虚假视频结果或费用。
- **Python**：ruff line-length=100，target py312；测试在 `apps/api/tests/`（pytest）。

## Provider 体系

`apps/api/app/providers/` 下按类型组织：
- 文本：`qwen_text.py`、`openai_compatible.py`、`mock.py`
- 图片：`qwen_image.py`、`openai_compatible_image.py`、`ark_seedream.py`、`google_genai_image.py`
- 视频：`local_h3_video.py`（本机 MiniMax H3，默认 `http://127.0.0.1:8787`）

Agent（`AGENT_PROVIDER`）可为 `qwen` / `openai_compatible` / `mock`，默认复用千问文本配置。
