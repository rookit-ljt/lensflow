"use client";

import { useEffect, useState } from "react";

import { AuthScreen } from "@/components/auth/auth-screen";
import { ProjectDashboard } from "@/components/dashboard/project-dashboard";
import { StudioWorkspace } from "@/components/studio-workspace";
import { ApiError, api, type CurrentUser } from "@/lib/api";

type AuthGateProps = {
  projectId?: string;
};

export function AuthGate({ projectId }: AuthGateProps) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api.getCurrentUser()
      .then((currentUser) => {
        if (active) setUser(currentUser);
      })
      .catch((cause) => {
        if (active && !(cause instanceof ApiError && cause.status === 401)) {
          setError(cause instanceof Error ? cause.message : "认证服务暂时不可用");
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => { active = false; };
  }, []);

  if (checking) {
    return (
      <main className="auth-loading" aria-label="正在验证登录状态">
        <span className="brand-mark">S</span><i /><p>正在进入工作区</p>
      </main>
    );
  }

  if (!user) return <AuthScreen initialError={error} onAuthenticated={setUser} />;

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setUser(null);
  };

  if (!projectId) return <ProjectDashboard currentUser={user} onLogout={logout} />;

  return <StudioWorkspace currentUser={user} projectId={projectId} onLogout={logout} />;
}
