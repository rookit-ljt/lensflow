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

生产对话入口为 `SimpleAgentRuntime.respond`：请求 JSON mode，先校验完整响应再发布文本。
需要模型/网关支持 `response_format: {"type":"json_object"}`。不是所有兼容网关都支持此能力；不支持时显示调用错误，不静默降级为猜选项。

```json
{
  "message": "先确认两个方向，再继续分镜。",
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

每个问题都必须回答或明确跳过；选项/自定义输入/跳过互斥。服务端校验后原子领取中断，重复提交返回 409。存储问题标题、选项标签、自定义文本和跳过记录，作为新的用户消息传回模型。恢复使用确切的决策消息 ID，避免同一秒的消息排序导致重放最初请求。

同一运行已答问题保存在模型上下文中；若再次返回相同标准化标题，要求模型修正，最多一次，防止重复弹窗。语义相同但标题不同仍依赖模型遵守上下文。

旧单选/多选中断仍可显示。旧标记/自然语言解析仅供旧运行适配器兼容，生产 `respond` 不再依赖关键词创建表单。

## 验证

```sh
cd apps/api
pytest -q tests/test_agent_questions.py tests/test_agent.py
```

覆盖三类题型、选项与 ID 校验、自定义和跳过、多轮恢复、重复提交、无效输出修复与重复问题拦截。演示模式 `AGENT_PROVIDER=mock` 下输入“孙悟空大战齐天大圣”可触发两题卡，不调用付费模型；回答后返回演示续聊消息。
