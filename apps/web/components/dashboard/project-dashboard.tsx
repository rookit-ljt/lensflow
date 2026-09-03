"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUpRight,
  CircleAlert,
  Clock3,
  LoaderCircle,
  LogOut,
  Plus,
  RefreshCw,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type CurrentUser, type ProjectSummary } from "@/lib/api";

type ProjectDashboardProps = {
  currentUser: CurrentUser;
  onLogout: () => Promise<void>;
};

function formatProjectDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

export function ProjectDashboard({ currentUser, onLogout }: ProjectDashboardProps) {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProjects = async () => {
    setLoading(true);
    setError(null);
    try {
      setProjects(await api.listProjects());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "项目列表读取失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadProjects();
  }, []);

  const createProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = projectName.trim();
    if (!name || creating) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api.createProject({ name, description: description.trim() });
      router.push(`/projects/${project.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "项目创建失败");
      setCreating(false);
    }
  };

  return (
    <main className="dashboard-shell dashboard-shell--minimal">
      <header className="dashboard-header">
        <div className="dashboard-brand" aria-label="AI Video Studio"><strong>AI Video Studio</strong></div>
        <div className="dashboard-account">
          <span className="dashboard-avatar">{currentUser.display_name.slice(0, 1).toUpperCase()}</span>
          {currentUser.email !== "local@localhost.invalid" ? <Tooltip>
            <TooltipTrigger render={<Button type="button" variant="ghost" size="icon" aria-label="退出登录" onClick={() => void onLogout()} />}>
              <LogOut />
            </TooltipTrigger>
            <TooltipContent>退出登录</TooltipContent>
          </Tooltip> : null}
        </div>
      </header>

      <div className="dashboard-minimal-content">
        <Card className="dashboard-project-creator dashboard-project-creator--minimal">
          <form onSubmit={createProject}>
            <h1>新建项目</h1>
              <div className="dashboard-project-creator__fields">
              <div>
                <Label htmlFor="project-name">项目名称</Label>
                <Input
                  id="project-name"
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  maxLength={160}
                  required
                  placeholder="项目名称"
                  autoComplete="off"
                />
              </div>
              <div>
                <Label htmlFor="project-description">简介（可选）</Label>
                <Textarea
                  id="project-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="项目简介"
                  rows={2}
                />
              </div>
            </div>
            <div className="dashboard-project-creator__footer dashboard-project-creator__footer--minimal">
              <Button type="submit" disabled={creating || !projectName.trim()}>
                {creating ? <LoaderCircle className="action-spinner" /> : <Plus />}新建
              </Button>
            </div>
          </form>
        </Card>

        <section className="dashboard-library dashboard-library--minimal" aria-labelledby="project-library-title">
        <div className="dashboard-section-heading">
          <h2 id="project-library-title">项目</h2>
          <div className="dashboard-section-heading__meta">
            <Button type="button" variant="ghost" size="icon-sm" aria-label="刷新项目" onClick={() => void loadProjects()} disabled={loading}><RefreshCw /></Button>
          </div>
        </div>

        {error ? (
          <Alert variant="destructive" className="dashboard-alert">
            <CircleAlert /><AlertTitle>无法完成操作</AlertTitle><AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="dashboard-project-grid">
          {loading ? Array.from({ length: 3 }, (_, index) => (
            <Card key={index} className="dashboard-project-card dashboard-project-card--loading">
              <Skeleton /><Skeleton /><Skeleton />
            </Card>
          )) : projects.map((project) => (
            <Card
              key={project.id}
              className="dashboard-project-card"
              role="button"
              tabIndex={0}
              onClick={() => router.push(`/projects/${project.id}`)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") router.push(`/projects/${project.id}`);
              }}
            >
              <div className="dashboard-project-card__body">
                <ArrowUpRight className="dashboard-project-card__open" />
                <h3>{project.name}</h3>
                {project.description ? <p>{project.description}</p> : null}
                <footer><span><Clock3 />{formatProjectDate(project.updated_at)}</span></footer>
              </div>
            </Card>
          ))}
        </div>
        {!loading && projects.length === 0 ? <div className="dashboard-empty">暂无项目</div> : null}
        </section>
      </div>
    </main>
  );
}
