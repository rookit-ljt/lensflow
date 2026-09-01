# LibTV Web Platform

面向浏览器的项目制 AI 视频创作平台。MVP 使用 Product Workflow、FastAPI、Celery/RabbitMQ 和可插拔模型 Provider，不依赖 ComfyUI 核心链路。

本项目以开源协作和本地优先开发为目标。发布前请阅读 [贡献指南](CONTRIBUTING.md)、[安全策略](SECURITY.md) 和 [许可证](LICENSE)。

## 目录

```text
apps/web                  Next.js 创作工作台
apps/api                  FastAPI 业务服务
packages/workflow-schema  前后端共享工作流协议
outputs/                  架构设计文档
```

## 本地启动

1. 复制环境变量：`cp .env.example .env`
2. 启动基础设施：`docker compose up -d postgres rabbitmq`
3. 安装前端依赖：`pnpm install`
4. 启动 Web：`pnpm dev`
5. 创建项目独立 Python 环境并安装 API：`pnpm api:setup`
6. 启动 API：`pnpm api:dev`

Web 默认运行在 `http://localhost:3000`，API 文档位于 `http://localhost:8000/docs`。

API 必须通过上述脚本启动。脚本固定使用 `apps/api/.venv`，避免调用到 Conda 或系统全局安装的 `uvicorn`。

Compose 会从 `.env` 读取 PostgreSQL 和 RabbitMQ 凭据；`.env.example` 中的值仅用于本地开发，生产部署必须替换为随机强密码。

## 当前阶段

- 已完成仓库和领域模型骨架。
- Web 工作台从 FastAPI 读取项目和镜头；示例项目、新增镜头与工作流编辑均写入数据库。
- 支持邮箱密码注册、登录和退出；会话使用 HttpOnly Cookie，项目、镜头、工作流、生成记录、Agent 对话和新上传素材按用户隔离。
- 升级已有数据库后，第一个注册账号会自动接管此前没有所属用户的本地项目，避免历史数据丢失。
- API 提供健康检查，以及项目、镜头、工作流的创建、查询和更新接口。
- 每个镜头拥有独立的持久化工作流；节点、连线、位置和视口都会在编辑后自动保存，刷新页面可以恢复。
- 工作流保存带有单调递增 `revision` 与 `operation_id`：客户端可基于版本做乐观并发控制，重复请求幂等，过期草稿返回 409 冲突。
- 工作流支持新增统一空白创作节点、拖拽、连线和删除；选中节点后再配置文本、图片或视频生成。音频节点保留协议兼容性，但暂未开放入口。
- 节点控制台可持久化 Prompt、模型预设、画幅、清晰度、质量、数量，以及不同生成类型的专属参数。
- 生成按钮创建持久化 Generation 记录，并通过 Celery 任务层执行零费用 Mock Provider。
- 右侧 Chat Agent 支持项目、镜头、选中节点、上下游连线和最近生成结果的上下文问答。
- Agent 对话按 Thread、Run、Message、Event 持久化；支持 SSE 增量回答、停止回答和部分内容恢复。
- 明确的画布操作会生成受限 CanvasPatch 预览；只有用户批准后才应用。当前支持修改生成节点配置、新增生成节点和连接节点，不会自动启动模型生成。
- Agent 也可以在审批后更新固定文本节点和提示词节点内容：文本节点写入 `text_content`，提示词节点写入 `detail`，生成节点继续写入 `prompt`/模型参数。
- Chat Agent 支持同一 Run 内的可恢复多轮确认：当前首条路径可先确认视觉画风，再继续生成角色与场景节点计划；选择卡片刷新后可恢复，确认记录会保留在对话中。
- Chat Agent 支持受控执行当前选中节点：用户明确要求“生成当前节点”后，Agent 先读取节点配置并展示模型调用确认；只有再次确认才创建 Generation，工具记录、任务状态和结果继续由画布跟踪。
- 项目资产库支持上传、浏览、搜索、类型筛选、下载、删除和插入当前生成节点；生成图片、生成视频和视频末帧会自动登记为项目资产，删除时会保护仍被画布引用的资产。
- Chat Agent 能读取项目资产目录，并在用户批准后将图片资产绑定到当前图片/视频节点，支持普通参考图、视频首帧和尾帧。
- Chat Agent 与节点提示词输入支持 `@` 引用选择器：可搜索并引用画布节点、项目资产、镜头和最近生成结果；发送时以结构化 `type/id/label` 传递，服务端会校验项目归属后注入 Agent 上下文。
- Chat Agent 内置 Skill 库：提供视频导演、稳定提示词、分镜连续性、H3 全参考、本地视频生产和剧本转漫画流程；支持搜索、收藏、来源跳转、选择启用和浏览器本地创建自定义 Skill。
- Agent 画布 Patch 携带 `base_revision` 与唯一 `operation_id`，审批应用前再次校验画布版本，避免覆盖用户在计划生成后的编辑。
- 真实视频模型和资产版本管理尚未接入，不展示虚假视频结果或费用。

## 任务执行模式

开发环境默认 `CELERY_TASK_ALWAYS_EAGER=true`，无需 RabbitMQ 即可验证任务创建、执行和状态回写。

要切换到独立 Worker：

1. 在 `.env` 设置 `CELERY_TASK_ALWAYS_EAGER=false`
2. 运行 `docker compose up -d rabbitmq`
3. 保持 `pnpm api:dev` 运行
4. 在另一个终端运行 `pnpm api:worker`

Mock Provider 只验证编排，不生成视频、不调用外部服务，也不会产生费用。

### 本地 MiniMax H3 视频模型

视频节点支持本机异步 H3 服务。根目录 `.env` 默认使用：

```env
LOCAL_VIDEO_BASE_URL=http://127.0.0.1:8787
LOCAL_VIDEO_MODEL=minimax-h3-local
LOCAL_VIDEO_REQUEST_TIMEOUT_SECONDS=1800
LOCAL_VIDEO_POLL_INTERVAL_SECONDS=2
```

服务启动后，新增空白节点并选择“视频生成 / 本地 MiniMax H3”。开发环境默认采用
`256 × 256、1 秒、4 步`，适合快速验证；也可在节点中切换 512、模型 `preview`
规格或 720P。将一至两张图片节点连接到视频节点后，可以分别指定首帧和尾帧；HTTP、
Data URL 或本地图片会由 API 服务准备成本机路径，并作为 `first_frame`、`last_frame`
提交给 H3。
接口任务在 API 后台执行，页面会轮询 Generation 状态，成功后直接在画布节点内播放
`/v1/jobs/{id}/video`。

## 图片模型

图片节点支持 `openai_compatible` 和 `ark_seedream` 两类服务端 Provider。配置均放在根目录 `.env`：

```env
IMAGE_PROVIDER=openai_compatible
IMAGE_API_KEY=your-key
IMAGE_BASE_URL=https://api.openai.com/v1
IMAGE_MODEL=dall-e-2
IMAGE_REQUEST_TIMEOUT_SECONDS=180
```

前端通过 `/api/providers` 获取配置状态，不会读取或暴露 API Key。`dall-e-2` 的非方形和 2K/4K 选项会在服务端收敛为其兼容的 `1024x1024`。
本地开发默认使用 SQLite；部署环境可切换 PostgreSQL。当前已提供 Mock、OpenAI-compatible、通义千问、Gemini、Seedream 和本地 H3 Provider，具体能力取决于环境变量和服务端配置。

### 千问文本与图片

千问使用独立配置，可以和现有文本、Seedream、Gemini 或 OpenAI-compatible 图片模型并存：

```env
QWEN_API_KEY=你的百炼_API_Key
QWEN_TEXT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TEXT_MODEL=qwen3.7-plus
QWEN_IMAGE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
QWEN_IMAGE_MODEL=qwen-image-plus
QWEN_IMAGE_EDIT_MODEL=qwen-image-2.0-pro
QWEN_REQUEST_TIMEOUT_SECONDS=300
QWEN_IMAGE_POLL_INTERVAL_SECONDS=1
```

如果你的百炼工作空间要求专属地址，把两个 Base URL 替换为控制台提供的
`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/...` 地址。配置后重启 API；使用独立
Celery Worker 时也要同时重启 Worker。前端只读取 Provider、模型名和配置状态，不会读取
`QWEN_API_KEY`。

图片节点提供 `qwen-image-2.0-pro`、`qwen-image-2.0`、`qwen-image-plus` 与
`qwen-image`。纯文生图可使用 Plus；检测到 1–3 张连线参考图时会自动切换到
`QWEN_IMAGE_EDIT_MODEL`，通过百炼多模态接口完成图片编辑或多图融合。

## 文本模型配置

文本节点支持 OpenAI Chat Completions 兼容接口。复制 `.env.example` 为 `.env`，然后填写：

```env
TEXT_PROVIDER=openai_compatible
TEXT_API_KEY=你的模型服务密钥
TEXT_BASE_URL=https://api.openai.com/v1
TEXT_MODEL=gpt-4.1-mini
```

`TEXT_BASE_URL` 和 `TEXT_MODEL` 可以替换为 DeepSeek、通义千问等兼容服务。密钥只由 FastAPI/Celery 后端读取，不会发送到浏览器或写入数据库。修改配置后需要重启 API；使用独立 Celery Worker 时也要同时重启 Worker。

### 工作台快速配置（本地/内测）

开发环境启动后，点击工作台顶部的齿轮按钮“模型设置”，即可填写文本或图片模型的服务商、模型名、Base URL 和 API Key。文本模型可以点击“测试连接”，图片模型只保存配置，避免测试动作产生计费请求。Key 不会回显，也不会写入项目数据库；设置页只在 `ENVIRONMENT=development` 且 `RUNTIME_SETTINGS_ENABLED=true` 时开放。

设置会写入根目录的 `.env` 并立即更新当前 API 进程。若使用独立 Celery Worker，请在保存后重启 Worker 使其读取最新配置。生产部署应关闭运行时设置，并改用平台 Secret 或环境变量注入。

## Chat Agent 配置

Chat Agent 默认复用千问文本配置，并保留独立的模型覆盖项：

```env
AGENT_PROVIDER=qwen
AGENT_MODEL=
AGENT_TEMPERATURE=0.45
AGENT_MAX_TOKENS=2800
AGENT_HISTORY_MESSAGES=20
```

`AGENT_PROVIDER` 可设为 `qwen`、`openai_compatible` 或 `mock`。`AGENT_MODEL` 为空时，
分别回退到 `QWEN_TEXT_MODEL` 或 `TEXT_MODEL`。Agent 的审批记录、CanvasPatch 和事件协议均使用
可序列化的稳定结构，后续可映射到 LangGraph Checkpointer、`interrupt()` 与 `resume`。

架构基线见 [outputs/libtv-web-architecture.md](outputs/libtv-web-architecture.md)。

## 安全与隐私

- 不要把 `.env`、API Key、OAuth Client Secret、数据库文件或用户上传媒体提交到 Git。
- 只复制 `.env.example` 创建本地配置，并在共享日志、截图和 Issue 中脱敏。
- 如果曾经把真实密钥提交到仓库或发送到聊天记录，请立即在对应服务商控制台撤销并重新生成。
- 自托管部署时，请自行配置 HTTPS、可信 CORS 来源、Cookie 安全属性、数据库备份和对象存储权限。

## 开源范围

仓库中的 LibTV 应用代码以 Apache-2.0 发布；第三方依赖、模型服务、外部 Skill 和示例素材仍受其各自许可证与服务条款约束。提交新的 Provider、Skill 或素材时，请在 Pull Request 中提供来源、许可证和再分发依据。
