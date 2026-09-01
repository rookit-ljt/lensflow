"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUpRight,
  CircleAlert,
  Clock3,
  FolderOpen,
  LoaderCircle,
  LogOut,
  Plus,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type CurrentUser, type ProjectSummary } from "@/lib/api";
import { demoShots } from "@/components/studio/studio-config";

type ProjectDashboardProps = {
  currentUser: CurrentUser;
  onLogout: () => Promise<void>;
};

const projectStatusLabel: Record<ProjectSummary["status"], string> = {
  draft: "创作中",
  active: "进行中",
  archived: "已归档",
};

function formatProjectDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function ProjectSignal({ seed }: { seed: string }) {
  const variant = seed.charCodeAt(0) % 3;
  return (
    <svg className={`dashboard-project-signal dashboard-project-signal--${variant}`} viewBox="0 0 360 150" aria-hidden="true">
      <path d="M62 46 C128 46 132 92 198 92 S272 58 326 58" />
      <rect x="24" y="28" width="78" height="38" rx="5" />
      <rect x="160" y="74" width="78" height="38" rx="5" />
      <rect x="294" y="40" width="42" height="36" rx="5" />
      <circle cx="102" cy="47" r="3" />
      <circle cx="160" cy="92" r="3" />
      <circle cx="238" cy="93" r="3" />
      <circle cx="294" cy="58" r="3" />
    </svg>
  );
}

export function ProjectDashboard({ currentUser, onLogout }: ProjectDashboardProps) {
  const router = useRouter();
  const dashboardRef = useRef<HTMLElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);
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
      await api.createShot(project.id, {
        sequence_number: 1,
        title: "开场镜头",
        description: "从这里建立故事的第一个画面。",
        duration_seconds: 5,
      });
      router.push(`/projects/${project.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "项目创建失败");
      setCreating(false);
    }
  };

  const createDemoProject = async () => {
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: "沿海失踪案 · 示例项目",
        description: "从示例镜头开始体验画布、Agent 和生成节点。",
      });
      for (const [index, shot] of demoShots.entries()) {
        await api.createShot(project.id, { ...shot, sequence_number: index + 1 });
      }
      router.push(`/projects/${project.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "示例项目创建失败");
      setCreating(false);
    }
  };

  const focusProjectCreator = () => {
    dashboardRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    nameInputRef.current?.focus();
  };

  return (
    <main ref={dashboardRef} className="dashboard-shell">
      <header className="dashboard-header">
        <div className="dashboard-brand" aria-label="Framefield">
          <span className="brand-mark">S</span>
          <div><strong>Framefield</strong><small>PROJECT ROOM</small></div>
        </div>
        <div className="dashboard-account">
          <div className="dashboard-account__copy">
            <strong>{currentUser.display_name}</strong>
            <small>{currentUser.email}</small>
          </div>
          <span className="dashboard-avatar">{currentUser.display_name.slice(0, 1).toUpperCase()}</span>
          <Tooltip>
            <TooltipTrigger render={<Button type="button" variant="ghost" size="icon" aria-label="退出登录" onClick={() => void onLogout()} />}>
              <LogOut />
            </TooltipTrigger>
            <TooltipContent>退出登录</TooltipContent>
          </Tooltip>
        </div>
      </header>

      <section className="dashboard-hero">
        <div className="dashboard-hero__heading">
          <p className="dashboard-eyebrow"><Sparkles /> YOUR STORY WORKSPACE</p>
          <h1>欢迎回来，<br /><span>{currentUser.display_name}</span></h1>
          <p>建立一个项目，把想法拆成镜头，再推进到每一帧。</p>
        </div>

        <Card className="dashboard-project-creator">
          <form onSubmit={createProject}>
            <div className="dashboard-project-creator__topline">
              <span>NEW PROJECT</span>
              <i>从一个明确的故事名称开始</i>
            </div>
            <div className="dashboard-project-creator__fields">
              <div>
                <Label htmlFor="project-name">项目名称</Label>
                <Input
                  ref={nameInputRef}
                  id="project-name"
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  maxLength={160}
                  required
                  placeholder="例如：海岸公路"
                  autoComplete="off"
                />
              </div>
              <div>
                <Label htmlFor="project-description">一句话简介</Label>
                <Textarea
                  id="project-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="故事发生在哪里，谁正在经历什么？"
                  rows={2}
                />
              </div>
            </div>
            <div className="dashboard-project-creator__footer">
              <span><Plus />创建后自动建立第一个镜头</span>
              <div className="dashboard-project-creator__actions">
                <Button type="button" variant="outline" size="sm" onClick={() => void createDemoProject()} disabled={creating}>
                  <Sparkles />试用示例
                </Button>
                <Button type="submit" size="icon-lg" disabled={creating || !projectName.trim()} aria-label="创建并进入项目">
                  {creating ? <LoaderCircle className="action-spinner" /> : <ArrowUpRight />}
                </Button>
              </div>
            </div>
          </form>
        </Card>
      </section>

      <section className="dashboard-library" aria-labelledby="project-library-title">
        <div className="dashboard-section-heading">
          <div><span>PROJECT LIBRARY</span><h2 id="project-library-title">历史项目</h2></div>
          <div className="dashboard-section-heading__meta">
            <Badge variant="outline">{projects.length} 个项目</Badge>
            <Button type="button" variant="ghost" size="sm" onClick={() => void loadProjects()} disabled={loading}><RefreshCw />刷新</Button>
          </div>
        </div>

        {error ? (
          <Alert variant="destructive" className="dashboard-alert">
            <CircleAlert /><AlertTitle>无法完成操作</AlertTitle><AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="dashboard-project-grid">
          <button type="button" className="dashboard-new-project" onClick={focusProjectCreator}>
            <span><Plus /></span><strong>创建新项目</strong><small>从空白镜头开始</small>
          </button>

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
              <div className="dashboard-project-card__preview"><ProjectSignal seed={project.id} /></div>
              <div className="dashboard-project-card__body">
                <div className="dashboard-project-card__status"><span>{projectStatusLabel[project.status]}</span><ArrowUpRight /></div>
                <h3>{project.name}</h3>
                <p>{project.description || "还没有填写项目简介。"}</p>
                <footer><span><Clock3 />{formatProjectDate(project.updated_at)}</span><span><FolderOpen />进入画布</span></footer>
              </div>
            </Card>
          ))}
        </div>
      </section>
    </main>
  );
}
