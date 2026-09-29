# Agent 问题卡与继续对话

需要用户回答时，采用统一分页问题卡，而不是让用户从长段聊天文字里找问题。

## 交互

- 一次 1–5 题，顶部显示当前题号，可前后翻页修改答案。
- 单选、多选、开放题；选择题也可切换为自定义答案。
- “跳过此题”明确记录未作选择，不等于同意任何操作。
- 收起只隐藏卡片；“继续回答”重新打开并保留当前页面的填写状态。
- 最后统一提交全部答案，自动恢复原 Agent 运行，无需再发送一句“继续”。
- 提交失败保留填写内容并显示错误；刷新页面会恢复待答问题，尚未提交的本地草稿不保证保留。
- 问题选择与画布审批、生成确认相互独立，不会因为回答或跳过问题直接启动付费生成。

## 服务端协议

生产入口 `SimpleAgentRuntime.respond` 采用分阶段双协议，先校验完整响应再发布文本：

- 千问聊天发送 `tools=[ask_user, plan_canvas]`、`tool_choice=auto`，一轮最多一个调用。无调用时校验普通回复，不通过关键词猜问题。
- 明确的画布操作仍使用现有 JSON 计划器；问题卡提交后的续聊使用 `AgentReply JSON`，保留 `next_action=plan_canvas`。
- 显式声明不支持 `tools` 的 400/422 允许降级 JSON。自动模式收到格式错误、空响应、截断、重复问题或虚假执行声明时，也会改用一次 JSON 请求修复（要求模型声明支持结构化输出）。鉴权、限流、网络、5xx、HTTP schema 拒绝不降级；一次工具请求加一次修复/降级，总预算最多两次。显式工具模式仍尝试一次工具修复；未知或多个工具调用直接拒绝。
- JSON 模式需要支持 `response_format: {"type":"json_object"}`。工具模式与 JSON mode 不在同一个请求混用；千问 Agent 关闭思考模式，避免恢复依赖未保存的推理轨迹。

消息格式参考[百炼 Function Calling 文档](https://help.aliyun.com/zh/model-studio/qwen-function-calling)。只开放表单暂停和受控计划路由，不开放任意工具执行。引用节点/资产与普通聊天遵循相同协议，不再按是否包含 `@` 特判。

### 从回答继续到审批

- `plan_canvas({"message":"准备首帧计划。"})` 与 JSON 的 `next_action=plan_canvas` 进入同一个服务端计划编译入口，不直接修改画布，也不自动批准。
- 当前会话历史中、同一镜头已提交的答案会带入新一轮短回复（如“已选中”），保留问题 ID、标题和答案，避免遗忘选择或重复提问。
- 没有选中节点时，计划提示明确禁止 `update_node_config` 和 `selected` 端点。计划校验失败可自动重写一次，模型须基于原目标选择新建或修改，服务端不擅自把修改动作转换为新建。
- 只有完整合法的计划才持久化为待审批卡；修复失败或取消不发布假审批、不修改节点、不创建生成任务。
- 用户批准后，现有执行接口会应用画布变更并启动符合条件的生成任务；审批卡明确提示可能产生模型费用。回答问题本身不等于批准。
- 响应错误日志只记录运行 ID、校验阶段与字段/错误类型，不记录原始模型文本、参考素材或 Key。格式降级记录 `protocol.fallback`，计划修复记录 `plan.repair`。

### 配置与能力检测

```env
AGENT_TOOL_PROTOCOL=auto
AGENT_MODEL_CAPABILITIES={}
```

`auto`：模型能力声明优先，其次 Provider 默认（千问启用工具；未知 OpenAI 兼容网关默认 JSON）。`tool_calling`：首次聊天显式启用工具。`json`：强制原有 JSON。无论首次模式如何，回答问题后的轮次仍走 JSON。Mock 保持演示行为。

按 `provider:model` 覆盖能力（配置声明，不是检测结论）：

```env
AGENT_MODEL_CAPABILITIES={"openai_compatible:my-model":{"tool_calling":true,"structured_output":true}}
```

模型需支持首次工具调用和后续 JSON 才能完成完整链路。声明 `structured_output=false` 时，用到 JSON 的轮次明确失败。

模型设置页勾选“测试工具调用”再点击“测试连接”，只发一次强制 `ask_user` 的文本请求，会消耗少量 Token；不保存 Key、不修改配置、不创建中断/节点/生成任务。结果只表示本次模型及网关的测试情况，不自动写能力配置。API 对应 `POST /api/settings/test` 的 `test_tool_calling=true`，结果包含 `tool_calling`。启动时不做付费探测。

### ask_user 参数

`AskUserArguments` 复用 `AgentQuestion`，固定版本、稳定 form/question ID；参数无效时最多修复一次，原始参数不展示在聊天文本中。

```json
{
  "schema_version": "1.0",
  "form_id": "creative_direction",
  "message": "开始前确认两个方向。",
  "title": "创作方向",
  "questions": [
    {"id": "creative.format", "title": "制作什么？", "kind": "single_select", "options": [
      {"id": "image", "label": "图片"}, {"id": "video", "label": "视频"}
    ]},
    {"id": "creative.setting", "title": "故事发生在哪里？", "kind": "text", "options": []}
  ]
}
```

现有 `AgentInterrupt.payload` 保存 `protocol`、`schema_version`、`form_id`、`tool_name`、`tool_call_id` 和原始 `tool_arguments`，无需新表/迁移。事件和消息 metadata 带协议、调用 ID；降级有 `protocol.fallback` 事件。UI 不渲染原始参数。

### JSON 兼容协议

```json
{
  "message": "先确认两个方向，再继续分镜。",
  "next_action": "reply",
  "questions": [
    {
      "id": "format",
      "title": "你想制作什么？",
      "description": "选择一个方向。",
      "kind": "single_select",
      "options": [
        {"id": "image", "label": "一张图片", "caption": "定格精彩瞬间"},
        {"id": "video", "label": "一段短视频", "caption": "连续的动作和镜头"}
      ]
    },
    {"id": "setting", "title": "故事发生在哪里？", "kind": "text", "options": []}
  ]
}
```

普通回答必须提供 `questions: []`，不会强制每轮提问。`AgentReply` 校验题目/选项数量、类型、唯一 ID 与长度；失败最多自动修复一次，再失败则明确结束本轮。模型的语义判断仍可能出错，不能承诺任何模型对所有问题都能百分百识别。

有效问题保存为 `AgentInterrupt(kind="question_form", decision_key="llm_questions")`，进入 `waiting_user`。SSE 先发完整消息，再发 `interrupt.created`；原始 JSON 不进入聊天增量。

恢复接口：`POST /api/agent/runs/{run_id}/resume`：

```json
{
  "interrupt_id": "实际中断 UUID",
  "response": {
    "answers": [
      {"question_id": "format", "option_ids": ["video"], "text": "", "skipped": false},
      {"question_id": "setting", "option_ids": [], "text": "花果山，傍晚", "skipped": false}
    ]
  }
}
```

每题必须回答或明确跳过；选项/自定义输入/跳过互斥。校验后原子领取中断，重复提交返回 409。UI 保留“我的回答”用户消息；JSON 中断继续作为用户消息，工具中断则重建完整的 `assistant.tool_calls` + `role=tool` 消息对，通过 `tool_call_id` 关联，答案含 form_id、题目和真实标签。不会重复发送 UI 决策文字，也不会留下孤立 Tool Result。即使历史窗口只剩答案，也从数据库恢复对应调用。使用确切的 `resume_message_id` 避免同秒排序重放。

同一运行已答问题保存在上下文中。工具模式检查稳定 form_id/question.id；JSON 续聊检查已答 question.id，并保留旧标题防重复逻辑。改写标题不能规避相同 ID 检查；模型同时换 ID 和措辞的语义重复仍无法百分百识别。

旧单选/多选中断仍可显示。旧标记/自然语言解析仅供旧运行适配器兼容，生产 `respond` 不再依赖关键词创建表单。

## 回答之后：真实画布审批

`next_action` 将聊天、问题与画布计划分开，默认 `reply` 兼容已有响应：

- `reply`：继续聊天或用 `questions` 提问；不得声称已经提交审批。
- `plan_canvas`：必要问题已答、用户需要创建或修改节点时，请求后端准备画布计划；必须 `questions: []`。

例如用户在问题卡中选择“确认，开始生成”后，模型可以返回：

```json
{
  "message": "准备首帧图片节点的变更计划。",
  "next_action": "plan_canvas",
  "questions": []
}
```

此信号不是操作授权，也不会直接创建节点或启动生成。后端进入 `planning`，结合完整会话及已答问题调用计划器，校验非空的白名单 `CanvasPatch`，持久化 `AgentApproval` 后才发布审批提示和 `approval.required`。问题卡的恢复与普通画布请求共用这一计划入口，不再因消息类型为 `decision` 而只能聊天。

审批卡显示在 **Agent 对话中**，不是画布节点。前端收到事件后滚动到审批卡；刷新也可从 `pending-approval` 恢复。用户批准后先应用变更，再对补丁中新增或修改的图片/视频生成节点创建 `Generation` 任务，并沿用普通“运行镜头”入口的 Provider 校验、排队、进度、取消、重试、输出资产和下载闭环。拒绝不改画布，也不创建任务。文本节点只更新内容，不会误触发媒体生成。

仅有“计划已提交审批”的普通文本不会生成审批卡。对这些无真实记录的审批声明，输出校验要求模型修正为结构化信号或普通回答，最多重试一次；不是根据文字猜测操作。计划为空、校验失败或用户中途取消时不发布审批卡，也不发布模型声称成功的文字。此检查不能替代模型的语义理解。

## 验证

```sh
cd apps/api
pytest -q tests/test_agent_tools.py tests/test_agent_questions.py tests/test_agent.py
```

覆盖三类题型、选项与 ID 校验、自定义和跳过、多轮恢复、重复提交、无效输出修复与重复问题拦截。演示模式 `AGENT_PROVIDER=mock` 下输入“孙悟空大战齐天大圣”可触发两题卡，不调用付费模型；回答后返回演示续聊消息。

审批回归使用模拟模型 HTTP 响应覆盖：问题回答 → 计划信号 → 真实审批记录/事件 → 批准后新增节点，以及拒绝、跳过、无效计划和中途取消；整个过程不调用付费模型、不创建生成任务。

Tool Calling 回归另外覆盖显式能力降级与两次请求上限、未知/多个工具拒绝、完整工具消息对重建、截短历史与旧 JSON 兼容、两个独立数据库连接同时领取中断只能成功一次，以及设置页的单次非破坏性测试。

2026-09-03 浏览器实测：隔离内存数据库、千问 `qwen3.7-plus`，完成问题卡弹出 → 收起/重开保留选择 → 刷新恢复待答问题 → 提交三题 → JSON 续聊 → 生成审批卡 → 批准后画布出现视频节点。设置页工具测试成功；没有启动图片/视频生成，也未写入用户配置或现有项目数据。
