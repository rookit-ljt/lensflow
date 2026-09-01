"use client";

import Script from "next/script";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, CircleAlert, Film, LoaderCircle, Play, ShieldCheck, Sparkles } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type CurrentUser } from "@/lib/api";

type AuthMode = "login" | "register";

type GoogleCredentialResponse = { credential?: string };

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (options: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: Record<string, string | number | boolean>,
          ) => void;
        };
      };
    };
  }
}

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim() ?? "";

type AuthScreenProps = {
  initialError?: string | null;
  onAuthenticated: (user: CurrentUser) => void;
};

export function AuthScreen({ initialError, onAuthenticated }: AuthScreenProps) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [submitting, setSubmitting] = useState(false);
  const [googleReady, setGoogleReady] = useState(false);
  const googleButtonRef = useRef<HTMLDivElement>(null);

  const authenticateWithGoogle = useCallback(async (response: GoogleCredentialResponse) => {
    if (!response.credential) {
      setError("Google 没有返回有效的登录凭证");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      onAuthenticated(await api.loginWithGoogle(response.credential));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Google 登录失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }, [onAuthenticated]);

  useEffect(() => {
    const target = googleButtonRef.current;
    const googleIdentity = window.google?.accounts.id;
    if (!target || !googleReady || !googleIdentity || !GOOGLE_CLIENT_ID) return;
    target.replaceChildren();
    googleIdentity.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: authenticateWithGoogle,
    });
    googleIdentity.renderButton(target, {
      type: "standard",
      theme: "filled_black",
      size: "large",
      text: "continue_with",
      shape: "rectangular",
      logo_alignment: "left",
      width: Math.min(400, target.clientWidth || 400),
      locale: "zh-CN",
    });
  }, [authenticateWithGoogle, googleReady]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const user = mode === "register"
        ? await api.register({
            email: email.trim(),
            password,
            display_name: displayName.trim(),
          })
        : await api.login({ email: email.trim(), password });
      onAuthenticated(user);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法完成登录，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-shell">
      <header className="auth-topbar">
        <div className="auth-brand" aria-label="Framefield">
          <span><Film /></span>
          <strong>Framefield</strong>
        </div>
        <div className="auth-topbar__meta">
          <span>AI FILM WORKSPACE</span>
          <i />
          <span><ShieldCheck />账号独立空间</span>
        </div>
      </header>

      <section className="auth-story" aria-label="Framefield 创作工作台">
        <div className="auth-story__copy">
          <p className="auth-kicker"><Sparkles /> FROM IDEA TO MOTION</p>
          <h1>故事从这里，<br /><em>继续生长。</em></h1>
          <p>在同一张无限画布里组织剧本、角色、镜头与生成结果。每次回来，都从上一次创作的位置继续。</p>
        </div>

        <div className="auth-sequence" aria-label="Framefield 创作流程预览">
          <div className="auth-sequence__head">
            <div><Play /><span>创作序列</span></div>
            <span>PROJECT / 01</span>
          </div>
          <div className="auth-sequence__track" aria-hidden="true">
            <article className="auth-shot auth-shot--brief">
              <small>01 / 剧本</small>
              <strong>暴雨中的重逢</strong>
              <p>城市天台 · 夜 · 远处霓虹</p>
            </article>
            <span className="auth-sequence__line"><i /></span>
            <article className="auth-shot auth-shot--visual">
              <small>02 / 画面</small>
              <div className="auth-shot__scene"><b /><b /><b /></div>
              <p>角色与场景一致性</p>
            </article>
            <span className="auth-sequence__line"><i /></span>
            <article className="auth-shot auth-shot--motion">
              <small>03 / 动态</small>
              <div className="auth-shot__motion"><Play /></div>
              <p>镜头缓慢向前推进</p>
            </article>
          </div>
          <div className="auth-sequence__foot"><span><i /> 工作区已自动保存</span><span>00:12:08</span></div>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-card__heading">
            <div className="auth-card__index">MEMBER ACCESS</div>
            <h2>{mode === "login" ? "欢迎回来" : "创建工作区"}</h2>
            <p>{mode === "login" ? "登录后继续你的镜头与项目。" : "创建账号，开始管理你的独立创作空间。"}</p>
          </div>

          <Tabs value={mode} onValueChange={(value) => {
            setMode(value as AuthMode);
            setError(null);
          }}>
            <TabsList className="auth-tabs">
              <TabsTrigger value="login">登录</TabsTrigger>
              <TabsTrigger value="register">注册</TabsTrigger>
            </TabsList>
          </Tabs>

          <form className="auth-form" onSubmit={submit}>
            {mode === "register" ? (
              <div className="auth-field">
                <Label htmlFor="display-name">显示名称</Label>
                <Input id="display-name" autoComplete="name" minLength={2} maxLength={80} required value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：镜头导演" />
              </div>
            ) : null}
            <div className="auth-field">
              <Label htmlFor="email">邮箱</Label>
              <Input id="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" />
            </div>
            <div className="auth-field">
              <div className="auth-field__label"><Label htmlFor="password">密码</Label><span>{mode === "register" ? "至少 8 位" : ""}</span></div>
              <Input id="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={mode === "register" ? 8 : 1} maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} placeholder="••••••••" />
            </div>

            {error ? (
              <Alert variant="destructive"><CircleAlert /><AlertTitle>无法继续</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>
            ) : null}

            <Button type="submit" size="lg" disabled={submitting} className="auth-submit">
              {submitting ? <LoaderCircle className="action-spinner" /> : <ArrowRight />}
              {submitting ? "正在验证" : mode === "login" ? "进入工作区" : "创建并进入"}
            </Button>
          </form>

          {GOOGLE_CLIENT_ID ? (
            <>
              <div className="auth-divider"><span>或</span></div>
              <div
                className={`auth-google${submitting ? " auth-google--disabled" : ""}`}
                aria-busy={submitting}
              >
                <div ref={googleButtonRef} className="auth-google__button" />
              </div>
            </>
          ) : null}
          <p className="auth-card__legal">继续即表示你同意仅将生成内容用于合法用途。账号会话与项目数据相互隔离。</p>
          {GOOGLE_CLIENT_ID ? (
            <Script
              src="https://accounts.google.com/gsi/client"
              strategy="afterInteractive"
              onReady={() => setGoogleReady(true)}
              onError={() => setError("Google 登录组件加载失败，请检查网络后重试")}
            />
          ) : null}
        </div>
      </section>
    </main>
  );
}
