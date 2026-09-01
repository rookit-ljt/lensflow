"use client";

import Script from "next/script";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, CircleAlert, LoaderCircle } from "lucide-react";

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
    <main className="auth-shell auth-shell--minimal">
      <header className="auth-minimal-header"><strong>LibTV</strong></header>
      <section className="auth-panel auth-panel--minimal">
        <div className="auth-card auth-card--minimal">
          <div className="auth-card__heading">
            <h1>{mode === "login" ? "登录" : "注册"}</h1>
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
              {submitting ? "处理中" : mode === "login" ? "登录" : "注册"}
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
