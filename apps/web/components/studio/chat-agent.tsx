"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  ArrowUp,
  Bot,
  Check,
  CircleAlert,
  GitBranch,
  LoaderCircle,
  MessageSquarePlus,
  Palette,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
  Sparkles,
  Square,
  Wrench,
  X,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MentionPicker, type MentionOption, type MentionRef } from "@/components/studio/mention-picker";
import { SkillLibrary, type ChatSkill } from "@/components/studio/skill-library";
import type { StudioFlowNode } from "@/components/studio/studio-types";
import {
  api,
  type AgentMention,
  type AgentApproval,
  type AgentEvent,
  type AgentInterrupt,
  type AgentMessage,
  type AgentRun,
  type AgentSkill,
  type AgentThread,
  type Generation,
  type Project,
  type ProjectAsset,
  type Shot,
} from "@/lib/api";

type ChatAgentProps = {
  open: boolean;
  project: Project;
  shot: Shot;
  node?: StudioFlowNode;
  nodes?: StudioFlowNode[];
  assets?: ProjectAsset[];
  generation?: Generation;
  canvasVersion?: string;
  canvasRevision?: number;
  canvasCenter?: { x: number; y: number };
  canvasSyncing?: boolean;
  onCanvasChanged: () => void | Promise<void>;
  onClose: () => void;
};

const terminalStatuses = new Set(["completed", "failed", "cancelled"]);

function renderInlineMarkdown(value: string): ReactNode[] {
  const tokens = value.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g).filter(Boolean);
  return tokens.map((token, index) => {
    if (token.startsWith("**") && token.endsWith("**")) {
      return <strong key={index}>{token.slice(2, -2)}</strong>;
    }
    if (token.startsWith("`") && token.endsWith("`")) {
      return <code key={index}>{token.slice(1, -1)}</code>;
    }
    if (token.startsWith("*") && token.endsWith("*")) {
      return <em key={index}>{token.slice(1, -1)}</em>;
    }
    // During streaming the closing marker may not have arrived yet. Hide
    // formatting tokens instead of exposing Markdown syntax to the user.
    return <span key={index}>{token.replaceAll("**", "").replace(/^#+\s*/, "")}</span>;
  });
}

function AgentMessageContent({ content }: { content: string }) {
  const blocks: ReactNode[] = [];
  const lines = content.replaceAll("\r", "").split("\n");
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let listType: "ul" | "ol" | null = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const current = paragraph;
    paragraph = [];
    blocks.push(
      <p key={`p-${blocks.length}`}>
        {current.map((line, index) => (
          <span key={index}>{renderInlineMarkdown(line)}{index < current.length - 1 ? <br /> : null}</span>
        ))}
      </p>,
    );
  };
  const flushList = () => {
    if (!listType || !listItems.length) return;
    const current = listItems;
    const key = `list-${blocks.length}`;
    blocks.push(listType === "ol"
      ? <ol key={key}>{current.map((item, index) => <li key={index}>{renderInlineMarkdown(item)}</li>)}</ol>
      : <ul key={key}>{current.map((item, index) => <li key={index}>{renderInlineMarkdown(item)}</li>)}</ul>);
    listItems = [];
    listType = null;
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    const quote = trimmed.match(/^>\s+(.+)$/);
    if (/^```(?:\w+)?$/.test(trimmed)) {
      flushParagraph();
      flushList();
    } else if (!trimmed) {
      flushParagraph();
      flushList();
    } else if (heading) {
      flushParagraph();
      flushList();
      blocks.push(<h3 key={`h-${blocks.length}`}>{renderInlineMarkdown(heading[2])}</h3>);
    } else if (/^_{3,}$|^-{3,}$|^\*{3,}$/.test(trimmed)) {
      flushParagraph();
      flushList();
      blocks.push(<hr key={`hr-${blocks.length}`} />);
    } else if (unordered || ordered) {
      flushParagraph();
      const nextType = ordered ? "ol" : "ul";
      if (listType && listType !== nextType) flushList();
      listType = nextType;
      listItems.push((ordered?.[1] ?? unordered?.[1]) as string);
    } else if (quote) {
      flushParagraph();
      flushList();
      blocks.push(<blockquote key={`quote-${blocks.length}`}>{renderInlineMarkdown(quote[1])}</blockquote>);
    } else {
      flushList();
      paragraph.push(trimmed);
    }
  });
  flushParagraph();
  flushList();

  return <div className="chat-agent__rich-text">{blocks}</div>;
}

function interruptFromMessage(message: AgentMessage): AgentInterrupt | null {
  const value = message.message_metadata.interrupt;
  return value && typeof value === "object" && "id" in value
    ? value as AgentInterrupt
    : null;
}

type DecisionCardProps = {
  interrupt: AgentInterrupt;
  active: boolean;
  selectedOptionId: string | null;
  loading: boolean;
  onSelect: (optionId: string) => void;
  onConfirm: () => void;
};

function DecisionCard({
  interrupt,
  active,
  selectedOptionId,
  loading,
  onSelect,
  onConfirm,
}: DecisionCardProps) {
  const options = interrupt.payload.options ?? [];
  const confirmedOptionId = interrupt.response?.option_id;
  const currentOptionId = active ? selectedOptionId : confirmedOptionId;
  const generationConfirmation = interrupt.payload.presentation === "generation_confirmation";
  return (
    <section className={`chat-agent__decision ${active ? "is-active" : "is-resolved"}`}>
      <header>
        <span>{generationConfirmation ? <Play /> : <Palette />}{interrupt.title}</span>
        <Badge variant="outline">{active ? "等待选择" : "已确认"}</Badge>
      </header>
      <p>{interrupt.description}</p>
      <div className="chat-agent__decision-grid" role="radiogroup" aria-label={interrupt.title}>
        {options.map((option) => {
          const selected = currentOptionId === option.id;
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              className={`chat-agent__decision-option tone-${option.tone ?? "slate"} ${selected ? "is-selected" : ""}`}
              disabled={!active || loading}
              onClick={() => onSelect(option.id)}
            >
              <i aria-hidden="true" />
              <strong>{option.label}</strong>
              <span>{option.caption}</span>
              {selected ? <Check /> : null}
            </button>
          );
        })}
      </div>
      {active ? (
        <Button type="button" onClick={onConfirm} disabled={!selectedOptionId || loading}>
          {loading ? <LoaderCircle className="animate-spin" /> : <Check />}
          {String(interrupt.payload.confirm_label ?? "确认选择")}
        </Button>
      ) : (
        <footer><Check />已确认“{interrupt.response?.label ?? "所选方案"}”</footer>
      )}
    </section>
  );
}

function messageFromEvent(event: AgentEvent, threadId: string): AgentMessage | null {
  const payload = event.payload;
  if (event.event_type !== "message.completed" || typeof payload.content !== "string") return null;
  const role = payload.role === "tool" || payload.role === "system" || payload.role === "user"
    ? payload.role
    : "assistant";
  return {
    id: typeof payload.message_id === "string" ? payload.message_id : crypto.randomUUID(),
    thread_id: threadId,
    run_id: event.run_id,
    role,
    content: payload.content,
    message_type: typeof payload.message_type === "string" ? payload.message_type : "text",
    message_metadata: typeof payload.message_metadata === "object" && payload.message_metadata
      ? payload.message_metadata as Record<string, unknown>
      : {},
    created_at: typeof payload.created_at === "string" ? payload.created_at : new Date().toISOString(),
  };
}

export function ChatAgent({
  open,
  project,
  shot,
  node,
  nodes = [],
  assets = [],
  generation,
  canvasVersion,
  canvasRevision,
  canvasCenter,
  canvasSyncing = false,
  onCanvasChanged,
  onClose,
}: ChatAgentProps) {
  const [thread, setThread] = useState<AgentThread | null>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [draftMentions, setDraftMentions] = useState<MentionRef[]>([]);
  const [skillCatalog, setSkillCatalog] = useState<AgentSkill[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<ChatSkill | null>(null);
  const [skillOpen, setSkillOpen] = useState(false);
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
  const [pendingInterrupt, setPendingInterrupt] = useState<AgentInterrupt | null>(null);
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null);
  const [interruptLoading, setInterruptLoading] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<AgentApproval | null>(null);
  const [decisionLoading, setDecisionLoading] = useState<"approve" | "reject" | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const loadConversation = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const threads = await api.listAgentThreads(project.id);
      const current = threads[0] ?? await api.createAgentThread(project.id, {
        title: `${project.name} · 创作 Agent`,
      });
      setThread(current);
      const [restoredMessages, approval, interrupt] = await Promise.all([
        api.listAgentMessages(current.id),
        api.getPendingAgentApproval(current.id),
        api.getPendingAgentInterrupt(current.id),
      ]);
      setMessages(restoredMessages);
      setPendingApproval(approval);
      setPendingInterrupt(interrupt);
      setSelectedOptionId(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Chat Agent 加载失败");
    } finally {
      setLoading(false);
    }
  }, [project.id, project.name]);

  useEffect(() => {
    if (open) void loadConversation();
  }, [loadConversation, open]);

  useEffect(() => {
    if (!open) return;
    void api.listAgentSkills().then(setSkillCatalog).catch(() => undefined);
  }, [open]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeRun, messages, open]);

  useEffect(() => () => eventSourceRef.current?.close(), []);

  const handleSkillSelect = useCallback((skill: ChatSkill | null) => {
    setSelectedSkill(skill);
    setSkillOpen(false);
    setError(null);
  }, []);

  const startNewThread = useCallback(async () => {
    if (activeRun || pendingApproval || pendingInterrupt) return;
    setLoading(true);
    setError(null);
    try {
      const next = await api.createAgentThread(project.id, {
        title: `${shot.title} · 新对话`,
      });
      setThread(next);
      setMessages([]);
      setPendingApproval(null);
      setPendingInterrupt(null);
      setSelectedOptionId(null);
      setDraft("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法新建对话");
    } finally {
      setLoading(false);
    }
  }, [activeRun, pendingApproval, pendingInterrupt, project.id, shot.title]);

  const finishRun = useCallback(async (runId: string) => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    if (thread) {
      try {
        setMessages(await api.listAgentMessages(thread.id));
        const completed = await api.getAgentRun(runId);
        if (completed.status === "failed") setError(completed.error ?? "Agent 运行失败");
      } catch {
        setError("Agent 已结束，但对话记录刷新失败");
      }
    }
    setActiveRun(null);
    setPendingInterrupt(null);
  }, [thread]);

  const subscribeToRun = useCallback((run: AgentRun, after = 0) => {
    eventSourceRef.current?.close();
    const source = new EventSource(api.agentEventStreamUrl(run.id, after), {
      withCredentials: true,
    });
    eventSourceRef.current = source;

    source.addEventListener("message.completed", (rawEvent) => {
      const event = JSON.parse((rawEvent as MessageEvent<string>).data) as AgentEvent;
      const assistantMessage = messageFromEvent(event, run.thread_id);
      if (assistantMessage) {
        setMessages((current) => [
          ...current.filter((message) => !(
            message.id === assistantMessage.id
            || message.id === `stream-${run.id}`
          )),
          assistantMessage,
        ]);
      }
    });
    source.addEventListener("message.delta", (rawEvent) => {
      const event = JSON.parse((rawEvent as MessageEvent<string>).data) as AgentEvent;
      const delta = typeof event.payload.delta === "string" ? event.payload.delta : "";
      if (!delta) return;
      const streamingId = `stream-${run.id}`;
      setMessages((current) => {
        const existing = current.find((message) => message.id === streamingId);
        if (existing) {
          return current.map((message) => message.id === streamingId
            ? { ...message, content: `${message.content}${delta}` }
            : message);
        }
        return [...current, {
          id: streamingId,
          thread_id: run.thread_id,
          run_id: run.id,
          role: "assistant",
          content: delta,
          message_type: "text",
          message_metadata: {},
          created_at: new Date().toISOString(),
        }];
      });
    });
    source.addEventListener("run.failed", (rawEvent) => {
      const event = JSON.parse((rawEvent as MessageEvent<string>).data) as AgentEvent;
      setError(typeof event.payload.error === "string" ? event.payload.error : "Agent 运行失败");
      void finishRun(run.id);
    });
    source.addEventListener("approval.required", (rawEvent) => {
      const event = JSON.parse((rawEvent as MessageEvent<string>).data) as AgentEvent;
      const approval = event.payload.approval;
      if (approval && typeof approval === "object" && "id" in approval) {
        setPendingApproval(approval as AgentApproval);
      }
      source.close();
      eventSourceRef.current = null;
      setActiveRun(null);
      if (thread) void api.listAgentMessages(thread.id).then(setMessages);
    });
    source.addEventListener("interrupt.created", (rawEvent) => {
      const event = JSON.parse((rawEvent as MessageEvent<string>).data) as AgentEvent;
      const interrupt = event.payload.interrupt;
      if (interrupt && typeof interrupt === "object" && "id" in interrupt) {
        setPendingInterrupt(interrupt as AgentInterrupt);
        setSelectedOptionId(null);
      }
      source.close();
      eventSourceRef.current = null;
      setActiveRun(null);
      if (thread) void api.listAgentMessages(thread.id).then(setMessages);
    });
    source.addEventListener("generation.created", () => {
      void onCanvasChanged();
    });
    source.addEventListener("run.completed", () => void finishRun(run.id));
    source.addEventListener("run.cancelled", () => void finishRun(run.id));
    source.onerror = () => {
      source.close();
      void api.getAgentRun(run.id).then((latest) => {
        if (terminalStatuses.has(latest.status)) void finishRun(run.id);
        else if (latest.status === "waiting_approval") {
          setPendingApproval(latest.approval);
          setActiveRun(null);
        }
        else if (latest.status === "waiting_user" && thread) {
          void api.getPendingAgentInterrupt(thread.id).then((interrupt) => {
            setPendingInterrupt(interrupt);
            setActiveRun(null);
          });
        }
        else setError("Agent 事件连接已断开，请稍后重试");
      }).catch(() => setError("Agent 事件连接失败"));
    };
  }, [finishRun, onCanvasChanged, thread]);

  const sendMessage = useCallback(async (value?: string) => {
    const content = (value ?? draft).trim();
    if (!content || !thread || activeRun || pendingApproval || pendingInterrupt || canvasSyncing) return;
    setError(null);
    setDraft("");
    const mentions: AgentMention[] = value ? [] : draftMentions;
    setDraftMentions([]);
    const optimisticMessage: AgentMessage = {
      id: `local-${crypto.randomUUID()}`,
      thread_id: thread.id,
      run_id: null,
      role: "user",
      content,
      message_type: "text",
      message_metadata: {},
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimisticMessage]);
    try {
      const run = await api.createAgentRun(thread.id, {
        message: content,
        context: {
          project_id: project.id,
          shot_id: shot.id,
          selected_node_ids: node ? [node.id] : [],
          canvas_version: canvasVersion,
          canvas_revision: canvasRevision,
          canvas_center: canvasCenter,
          mentions,
          ...(selectedSkill ? {
            skill_id: selectedSkill.id,
            ...(selectedSkill.origin === "custom" ? { skill_prompt: selectedSkill.instruction } : {}),
          } : {}),
        },
      });
      setActiveRun(run);
      subscribeToRun(run);
    } catch (cause) {
      setMessages((current) => current.filter((message) => message.id !== optimisticMessage.id));
      setDraft(content);
      setError(cause instanceof Error ? cause.message : "消息发送失败");
    }
  }, [activeRun, canvasCenter, canvasRevision, canvasSyncing, canvasVersion, draft, draftMentions, node, pendingApproval, pendingInterrupt, project.id, selectedSkill, shot.id, subscribeToRun, thread]);

  const cancelRun = useCallback(async () => {
    if (!activeRun) return;
    setError(null);
    try {
      await api.cancelAgentRun(activeRun.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "停止 Agent 失败");
    }
  }, [activeRun]);

  const quickPrompts = useMemo(() => [
    node ? "分析当前节点并给出优化建议" : "分析当前镜头的创作方向",
    "为当前镜头生成角色及场景设计",
    node ? "生成当前节点" : "优化当前镜头提示词",
  ], [node]);

  const resumeInterrupt = useCallback(async () => {
    if (!pendingInterrupt || !selectedOptionId || interruptLoading || !thread) return;
    setInterruptLoading(true);
    setError(null);
    try {
      const result = await api.resumeAgentInterrupt(pendingInterrupt.run_id, {
        interrupt_id: pendingInterrupt.id,
        response: { option_id: selectedOptionId },
      });
      setPendingInterrupt(null);
      setSelectedOptionId(null);
      setMessages(await api.listAgentMessages(thread.id));
      setActiveRun(result.run);
      subscribeToRun(result.run, result.event_cursor);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法继续当前任务");
    } finally {
      setInterruptLoading(false);
    }
  }, [interruptLoading, pendingInterrupt, selectedOptionId, subscribeToRun, thread]);

  const decideApproval = useCallback(async (decision: "approve" | "reject") => {
    if (!pendingApproval || decisionLoading) return;
    setDecisionLoading(decision);
    setError(null);
    try {
      await api.decideAgentApproval(pendingApproval.run_id, { decision });
      setPendingApproval(null);
      if (thread) setMessages(await api.listAgentMessages(thread.id));
      if (decision === "approve") await onCanvasChanged();
    } catch (cause) {
      setPendingApproval(null);
      if (thread) setMessages(await api.listAgentMessages(thread.id));
      setError(cause instanceof Error ? cause.message : "画布变更处理失败");
    } finally {
      setDecisionLoading(null);
    }
  }, [decisionLoading, onCanvasChanged, pendingApproval, thread]);

  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const modelLabel = typeof lastAssistant?.message_metadata.model === "string"
    ? lastAssistant.message_metadata.model
    : "项目上下文";
  const streamingAnswer = Boolean(activeRun && messages.some((message) => (
    message.run_id === activeRun.id && message.role === "assistant"
  )));
  const agentStatusLabel = activeRun
    ? ({
        load_context: "正在读取项目和画布",
        compose_response: "正在组织回答",
        compile_canvas_patch: "正在生成画布计划",
        wait_for_approval: "等待你确认画布变更",
        execute_canvas_patch: "正在应用画布变更",
        persist_message: "正在保存对话",
      } as Record<string, string>)[activeRun.current_step] ?? "Agent 正在处理"
    : pendingInterrupt
      ? "请先完成上方创作选择"
      : pendingApproval
        ? "请先确认上方画布变更"
        : canvasSyncing
          ? "正在同步画布，请稍候"
          : "Enter 发送 · Shift + Enter 换行";

  const mentionOptions = useMemo<MentionOption[]>(() => [
    ...nodes.map((canvasNode) => ({
      type: "node" as const,
      id: canvasNode.id,
      label: canvasNode.data.title,
      kind: canvasNode.data.kind,
      subtitle: canvasNode.data.detail || canvasNode.data.kind,
    })),
    ...assets.map((asset) => ({
      type: "asset" as const,
      id: asset.id,
      label: asset.filename,
      kind: asset.kind,
      subtitle: `${asset.role === "last_frame" ? "视频末帧 · " : ""}${asset.kind === "video" ? "视频" : asset.kind === "audio" ? "音频" : "图片"}`,
    })),
    ...(generation ? [{
      type: "generation" as const,
      id: generation.id,
      label: `最近${generation.kind === "video" ? "视频" : generation.kind === "image" ? "图片" : "文本"}结果`,
      kind: generation.kind,
      subtitle: generation.status === "succeeded" ? "已完成，可作为参考" : generation.status,
    }] : []),
    ...project.shots.map((projectShot) => ({
      type: "shot" as const,
      id: projectShot.id,
      label: projectShot.title,
      subtitle: `镜头 ${String(projectShot.sequence_number).padStart(2, "0")}`,
    })),
  ], [assets, generation, nodes, project.shots]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  };

  return (
    <aside className={`chat-agent ${open ? "is-open" : ""}`} aria-label="Chat Agent" aria-hidden={!open}>
      <header className="chat-agent__header">
        <div className="chat-agent__identity">
          <span className="chat-agent__mark"><Bot /></span>
          <div><span>CHAT AGENT</span><h2>创作 Agent</h2></div>
        </div>
        <div className="chat-agent__header-actions">
          <Button type="button" variant="ghost" size="icon" onClick={() => setSkillOpen(true)} aria-label="打开 Skill 库"><Sparkles /></Button>
          <Button type="button" variant="ghost" size="icon" onClick={() => void startNewThread()} disabled={Boolean(activeRun || pendingApproval || pendingInterrupt)} aria-label="新建对话"><MessageSquarePlus /></Button>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="关闭 Chat Agent"><X /></Button>
        </div>
      </header>

      <SkillLibrary
        open={skillOpen}
        skills={skillCatalog}
        selectedSkillId={selectedSkill?.id}
        onSelect={handleSkillSelect}
        onClose={() => setSkillOpen(false)}
      />

      <section className="chat-agent__context" aria-label="当前上下文">
        <div className="chat-agent__context-heading"><span>SCENE {String(shot.sequence_number).padStart(2, "0")}</span><Badge variant="outline">{modelLabel}</Badge></div>
        <strong>{shot.title}</strong>
        <div className="chat-agent__context-tags">
          <span>{project.name}</span>
          {node ? <span>{node.data.title}</span> : <span>未选中节点</span>}
          {generation ? <span>{generation.status}</span> : null}
        </div>
      </section>

      <ScrollArea className="chat-agent__messages">
        <div className="chat-agent__message-list">
          {loading ? (
            <div className="chat-agent__loading"><LoaderCircle />正在恢复对话</div>
          ) : messages.length === 0 ? (
            <div className="chat-agent__empty">
              <Sparkles />
              <h3>从当前镜头开始</h3>
              <p>告诉我你想改什么。我会先给出计划，确认后再更新画布。</p>
            </div>
          ) : messages.map((message) => {
            const messageInterrupt = interruptFromMessage(message);
            const displayRole = message.role === "user" ? "user" : "assistant";
            return (
              <div key={message.id} className="chat-agent__message-group">
                <article className={`chat-agent__message chat-agent__message--${displayRole} ${message.role === "tool" ? "chat-agent__message--tool" : ""}`}>
                  <span>{message.role === "tool" ? <><Wrench /> TOOL</> : message.role === "assistant" ? "AGENT" : "YOU"}</span>
                  {message.role === "assistant"
                    ? <AgentMessageContent content={message.content} />
                    : <div>{message.content}</div>}
                  {message.message_metadata.cancelled === true ? <em>回答已停止</em> : null}
                </article>
                {messageInterrupt ? (
                  <DecisionCard
                    interrupt={pendingInterrupt?.id === messageInterrupt.id ? pendingInterrupt : messageInterrupt}
                    active={pendingInterrupt?.id === messageInterrupt.id}
                    selectedOptionId={selectedOptionId}
                    loading={interruptLoading}
                    onSelect={setSelectedOptionId}
                    onConfirm={() => void resumeInterrupt()}
                  />
                ) : null}
              </div>
            );
          })}
          {pendingApproval ? (
            <section className="chat-agent__approval" aria-label="待确认的画布变更">
              <header>
                <span><ShieldCheck />待确认的画布变更</span>
                <Badge variant="outline">LOW RISK</Badge>
              </header>
              <p>{pendingApproval.summary}</p>
              <div className="chat-agent__approval-operations">
                {pendingApproval.patch.operations.map((operation) => (
                  <div key={operation.id}>
                    {operation.type === "update_node_config" ? <Pencil /> : operation.type === "create_node" ? <Plus /> : operation.type === "bind_asset" ? <Wrench /> : <GitBranch />}
                    <span>{operation.description}</span>
                  </div>
                ))}
              </div>
              <footer>
                <span>不会启动模型生成或产生调用费用</span>
                <div>
                  <Button type="button" variant="ghost" onClick={() => void decideApproval("reject")} disabled={Boolean(decisionLoading)}>
                    {decisionLoading === "reject" ? <LoaderCircle className="animate-spin" /> : null}取消
                  </Button>
                  <Button type="button" onClick={() => void decideApproval("approve")} disabled={Boolean(decisionLoading)}>
                    {decisionLoading === "approve" ? <LoaderCircle className="animate-spin" /> : <Check />}应用到画布
                  </Button>
                </div>
              </footer>
            </section>
          ) : null}
          {activeRun && !streamingAnswer ? (
            <div className="chat-agent__thinking"><i /><i /><i /><span>正在读取画布并组织回答</span></div>
          ) : null}
          <div ref={endRef} />
        </div>
      </ScrollArea>

      <div className="chat-agent__footer">
        {error ? (
          <Alert variant="destructive" className="chat-agent__error"><CircleAlert /><AlertDescription>{error}</AlertDescription></Alert>
        ) : null}
        {messages.length === 0 && !loading ? (
          <div className="chat-agent__quick-prompts">
            {quickPrompts.map((prompt) => (
              <Button key={prompt} type="button" variant="outline" onClick={() => void sendMessage(prompt)} disabled={!thread || canvasSyncing || Boolean(activeRun || pendingApproval || pendingInterrupt)}>{prompt}</Button>
            ))}
          </div>
        ) : null}
        {selectedSkill ? (
          <div className="chat-agent__active-skill" role="status" aria-live="polite">
            <span className="chat-agent__active-skill-mark"><Sparkles /></span>
            <span className="chat-agent__active-skill-copy">
              <strong>已启用 {selectedSkill.name}</strong>
              <small>下一条消息会按照此 Skill 的流程和规则处理</small>
            </span>
            <button type="button" onClick={() => setSelectedSkill(null)} aria-label={`停用 ${selectedSkill.name}`}><X /></button>
          </div>
        ) : null}
        <div className="chat-agent__composer">
          <MentionPicker
            wrapperClassName="chat-agent__mention-picker"
            value={draft}
            options={mentionOptions}
            mentions={draftMentions}
            onMentionsChange={setDraftMentions}
            onChange={setDraft}
            onKeyDown={handleKeyDown}
            placeholder={node ? `修改「${node.data.title}」…` : "告诉 Agent 下一步…"}
            disabled={!thread || canvasSyncing || Boolean(activeRun || pendingApproval || pendingInterrupt)}
            rows={3}
          />
          <div className="chat-agent__composer-meta">
            <span className="chat-agent__composer-status">{activeRun ? `${agentStatusLabel} · 点击停止` : agentStatusLabel}</span>
            <button type="button" className={`chat-agent__skill-chip ${selectedSkill ? "is-selected" : ""}`} onClick={() => setSkillOpen(true)}><Sparkles />{selectedSkill?.name ?? "选择 Skill"}</button>
            <Button
              type="button"
              size="icon"
              variant={activeRun ? "outline" : "default"}
              className={activeRun ? "chat-agent__stop" : undefined}
              onClick={() => activeRun ? void cancelRun() : void sendMessage()}
              disabled={activeRun ? false : canvasSyncing || Boolean(pendingApproval || pendingInterrupt) || !draft.trim() || !thread}
              aria-label={activeRun ? "停止回答" : "发送消息"}
            >
              {activeRun ? <Square /> : <ArrowUp />}
            </Button>
          </div>
        </div>
      </div>
    </aside>
  );
}
