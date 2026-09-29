"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, Bot, LoaderCircle, Sparkles, X } from "lucide-react";
import { AuthScreen } from "@/components/auth/auth-screen";
import { ApiError, api } from "@/lib/api";
import type { InspirationCase } from "@/data/inspiration-cases";

export function HomeComposer({
  prefillPrompt,
  activeCase,
  onClearCase,
}: {
  prefillPrompt?: string;
  activeCase?: InspirationCase | null;
  onClearCase?: (caseId: number) => void;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState(prefillPrompt ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [login, setLogin] = useState(false);
  const lock = useRef(false);
    // Keep successful setup steps on retry, so a run failure doesn't create another project.
  const pending = useRef<{ projectId?: string; shotId?: string; threadId?: string }>({});

    // 外部（灵感案例点击）注入 prompt：变化时覆盖 draft
  useEffect(() => {
    if (prefillPrompt) setDraft(prefillPrompt);
    }, [prefillPrompt]);

  async function send() {
    const message = draft.trim();
    if (!message || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      await api.getCurrentUser();
      const state = pending.current;
      if (!state.projectId) {
        const project = await api.createProject({ name: message.slice(0, 36), description: "由首页 Agent 对话创建" });
        state.projectId = project.id;
        }
      if (!state.shotId) {
        const shot = await api.createShot(state.projectId, {
          sequence_number: 1, title: "第一个镜头", description: "由 Chat Agent 根据创意生成。",
          visual_prompt: message.slice(0, 12000), duration_seconds: 5,
          });
        state.shotId = shot.id;
        }
      await api.getWorkflow(state.shotId, { empty: true });
      if (!state.threadId) {
        const thread = await api.createAgentThread(state.projectId, { title: `${message.slice(0, 36)} · 创作 Agent` });
        state.threadId = thread.id;
        }
        // A lost HTTP response may still have created the run. Recover it instead of resending.
      const messages = await api.listAgentMessages(state.threadId);
      if (!messages.some(item => item.role === "user")) {
        await api.createAgentRun(state.threadId, {
          message,
          context: { project_id: state.projectId, shot_id: state.shotId, selected_node_ids: [], mentions: [] },
          });
        }
      router.push(`/projects/${state.projectId}?chat=1`);
        // Keep the form locked until navigation unmounts it.
      return;
      } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) setLogin(true);
      else setError(cause instanceof Error ? cause.message : "发送失败，请重试");
      }
    lock.current = false;
    setBusy(false);
    }

  function submit(event: FormEvent) { event.preventDefault(); void send(); }

  return <>
    <form className="home-agent" onSubmit={submit} aria-label="首页 Agent 对话">
        <div className="home-agent-heading"><Bot size={19} /><strong>Agent Chat</strong><span>{activeCase ? `已填入「${activeCase.keywords}」` : "图片 · 视频 · 创作规划"}</span></div>
        {activeCase ? (
          <div className="home-agent-case-chip">
            <Sparkles size={14} />
            <strong>{activeCase.keywords}</strong>
            {activeCase.size ? <span className="home-agent-case-chip-sub">{activeCase.size}</span> : null}
            {activeCase.qualityLevel ? <span className="home-agent-case-chip-sub">{activeCase.qualityLevel}</span> : null}
            <button
            type="button"
            aria-label={`移除已填入的「${activeCase.keywords}」案例`}
            onClick={() => {
              setDraft("");
              if (onClearCase) onClearCase(activeCase.id);
              }}
            ><X size={14} /></button>
          </div>
        ) : null}
        <textarea aria-label="发给 Agent 的消息" placeholder="描述你想创作的内容，Agent 会帮你开始。" value={draft}
        onChange={event => setDraft(event.target.value)} disabled={busy} rows={3} maxLength={12000}
        onKeyDown={event => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); }
          }} />
        {error && <p className="home-agent-error" role="alert">{error}。可以重试，已创建的项目会继续使用。</p>}
        <div className="home-agent-footer"><span>{busy ? "正在创建项目并发送消息…" : "发送后自动创建项目 · Shift + Enter 换行"}</span>
          <button type="submit" aria-label="发送并创建项目" disabled={busy || !draft.trim()}>{busy ? <LoaderCircle size={22} className="animate-spin" /> : <ArrowUp size={24} />}</button>
        </div>
      </form>
      {login && <div className="home-agent-auth" role="dialog" aria-modal="true" aria-label="登录后继续对话">
        <button className="home-agent-auth-close" aria-label="取消登录" onClick={() => setLogin(false)}><X />返回首页</button>
        <AuthScreen initialError="请先登录，你输入的消息已保留。" onAuthenticated={() => { setLogin(false); void send(); }} />
      </div>}
    </>;
}
