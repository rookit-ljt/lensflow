"use client";

import { type FormEvent, type MouseEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUpRight,
  CircleAlert,
  Clock3,
  Download,
  ExternalLink,
  Film,
  FolderArchive,
  Image as ImageIcon,
  LoaderCircle,
  LogOut,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type CurrentUser, type ProjectAsset, type ProjectSummary } from "@/lib/api";

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

function formatAssetSize(size: number): string {
  if (!size) return "云端资源";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function ProjectDashboard({ currentUser, onLogout }: ProjectDashboardProps) {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  // 弹窗状态
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [assetsModalOpen, setAssetsModalOpen] = useState(false);

  // 素材库状态
  const [assets, setAssets] = useState<ProjectAsset[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetFilter, setAssetFilter] = useState<"all" | "image" | "video">("all");
  const [assetSearch, setAssetSearch] = useState("");

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

  const loadUserAssets = async () => {
    setAssetsLoading(true);
    try {
      const data = await api.listUserAssets({
        kind: assetFilter === "all" ? undefined : assetFilter,
        q: assetSearch.trim() || undefined,
      });
      setAssets(data);
    } catch (cause) {
      console.error("加载素材库失败:", cause);
    } finally {
      setAssetsLoading(false);
    }
  };

  useEffect(() => {
    void loadProjects();
  }, []);

  useEffect(() => {
    if (assetsModalOpen) {
      void loadUserAssets();
    }
  }, [assetsModalOpen, assetFilter, assetSearch]);

  const handleOpenCreateModal = () => {
    setProjectName("");
    setDescription("");
    setError(null);
    setCreateModalOpen(true);
  };

  const handleOpenAssetsModal = () => {
    setAssetsModalOpen(true);
  };

  const createProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = projectName.trim();
    if (!name || creating) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api.createProject({ name, description: description.trim() });
      setCreateModalOpen(false);
      router.push(`/projects/${project.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "项目创建失败");
      setCreating(false);
    }
  };

  const deleteProject = async (event: MouseEvent, project: ProjectSummary) => {
    event.stopPropagation();
    if (deletingProjectId) return;
    const confirmed = window.confirm(`确定删除项目“${project.name}”？\n项目中的镜头、素材和生成记录都会被永久删除。`);
    if (!confirmed) return;
    setDeletingProjectId(project.id);
    setError(null);
    try {
      await api.deleteProject(project.id);
      setProjects((current) => current.filter((item) => item.id !== project.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "项目删除失败");
    } finally {
      setDeletingProjectId(null);
    }
  };

  const filteredProjects = projects.filter((project) =>
    project.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <main className="dashboard-shell dashboard-shell--minimal">
      {/* 左侧功能栏 */}
      <aside className="project-sidebar" aria-label="快捷导航">
        <Tooltip>
          <TooltipTrigger render={
            <Button
              type="button"
              aria-label="新建项目"
              onClick={handleOpenCreateModal}
            >
              <Plus />
            </Button>
          } />
          <TooltipContent side="right">新建项目</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger render={
            <Button
              type="button"
              aria-label="回到首页"
              onClick={() => router.push("/")}
            >
              <span>⌂</span>
            </Button>
          } />
          <TooltipContent side="right">回到首页</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger render={
            <Button
              type="button"
              aria-label="项目列表"
              className="active"
              onClick={() => {
                window.scrollTo({ top: 0, behavior: "smooth" });
                void loadProjects();
              }}
            >
              <span>▱</span>
            </Button>
          } />
          <TooltipContent side="right">刷新项目列表</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger render={
            <Button
              type="button"
              aria-label="我的素材库"
              onClick={handleOpenAssetsModal}
            >
              <span>▦</span>
            </Button>
          } />
          <TooltipContent side="right">我的素材库</TooltipContent>
        </Tooltip>
      </aside>

      <header className="dashboard-header">
        <div className="dashboard-brand" aria-label="AI Video Studio"><strong>灵感工场</strong></div>
        <div className="dashboard-account">
          <span className="dashboard-avatar">{currentUser.display_name.slice(0, 1).toUpperCase()}</span>
          {currentUser.email !== "local@localhost.invalid" ? (
            <Tooltip>
              <TooltipTrigger render={
                <Button type="button" variant="ghost" size="icon" aria-label="退出登录" onClick={() => void onLogout()} />
              }>
                <LogOut />
              </TooltipTrigger>
              <TooltipContent>退出登录</TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      </header>

      <div className="dashboard-minimal-content">
        <div className="project-heading">
          <h1>我的项目</h1>
          <label>
            <Search size={22} />
            <input
              aria-label="搜索项目"
              placeholder="搜索项目"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>

        <section className="dashboard-library dashboard-library--minimal" aria-labelledby="project-library-title">
          <div className="dashboard-section-heading">
            <h2 id="project-library-title">项目</h2>
            <div className="dashboard-section-heading__meta">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="刷新项目"
                onClick={() => void loadProjects()}
                disabled={loading}
              >
                <RefreshCw />
              </Button>
            </div>
          </div>

          {error ? (
            <Alert variant="destructive" className="dashboard-alert mb-6">
              <CircleAlert />
              <AlertTitle>无法完成操作</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <div className="dashboard-project-grid">
            {!loading && !search && (
              <Card
                className="dashboard-project-card project-new-tile cursor-pointer transition-transform hover:scale-[1.02]"
                role="button"
                tabIndex={0}
                onClick={handleOpenCreateModal}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") handleOpenCreateModal();
                }}
              >
                <Plus size={34} />
                <span>新建项目</span>
              </Card>
            )}

            {loading
              ? Array.from({ length: 3 }, (_, index) => (
                  <Card key={index} className="dashboard-project-card dashboard-project-card--loading">
                    <Skeleton />
                    <Skeleton />
                    <Skeleton />
                  </Card>
                ))
              : filteredProjects.map((project) => (
                  <Card
                    key={project.id}
                    className="dashboard-project-card"
                    role="button"
                    tabIndex={0}
                    onClick={() => router.push(`/projects/${project.id}`)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        router.push(`/projects/${project.id}`);
                      }
                    }}
                  >
                    <div className="dashboard-project-card__body">
                      <ArrowUpRight className="dashboard-project-card__open" />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        className="dashboard-project-card__delete"
                        aria-label={`删除项目 ${project.name}`}
                        disabled={deletingProjectId === project.id}
                        onClick={(event) => void deleteProject(event, project)}
                      >
                        {deletingProjectId === project.id ? (
                          <LoaderCircle className="action-spinner" />
                        ) : (
                          <Trash2 />
                        )}
                      </Button>
                      <h3>{project.name}</h3>
                      {project.description ? <p>{project.description}</p> : null}
                      <footer>
                        <span>
                          <Clock3 />
                          {formatProjectDate(project.updated_at)}
                        </span>
                      </footer>
                    </div>
                  </Card>
                ))}
          </div>

          {!loading && projects.length === 0 ? <div className="dashboard-empty">暂无项目</div> : null}
        </section>
      </div>

      {/* 新建项目弹窗 Dialog */}
      {createModalOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-project-title"
          onClick={() => !creating && setCreateModalOpen(false)}
        >
          <Card
            className="w-full max-w-lg border border-white/10 bg-zinc-950 text-zinc-100 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 pb-4">
              <CardTitle id="create-project-title" className="text-xl font-medium">新建项目</CardTitle>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setCreateModalOpen(false)}
                disabled={creating}
              >
                <X className="size-5" />
              </Button>
            </CardHeader>
            <form onSubmit={createProject}>
              <CardContent className="space-y-4 pt-5">
                <div>
                  <Label htmlFor="modal-project-name" className="text-sm font-medium text-zinc-300">
                    项目名称 <span className="text-red-400">*</span>
                  </Label>
                  <Input
                    id="modal-project-name"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    maxLength={160}
                    required
                    autoFocus
                    placeholder="例如：赛博朋克短片、产品发布会宣传片"
                    className="mt-1.5 bg-zinc-900 border-white/10 text-white placeholder:text-zinc-500"
                  />
                </div>
                <div>
                  <Label htmlFor="modal-project-desc" className="text-sm font-medium text-zinc-300">
                    项目简介（可选）
                  </Label>
                  <Textarea
                    id="modal-project-desc"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="简单描述项目的创作主题或风格"
                    rows={3}
                    className="mt-1.5 bg-zinc-900 border-white/10 text-white placeholder:text-zinc-500 resize-none"
                  />
                </div>
                {error && (
                  <p className="text-xs text-red-400">{error}</p>
                )}
              </CardContent>
              <div className="flex items-center justify-end gap-3 border-t border-white/10 px-6 py-4">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setCreateModalOpen(false)}
                  disabled={creating}
                >
                  取消
                </Button>
                <Button
                  type="submit"
                  disabled={creating || !projectName.trim()}
                  className="bg-white text-zinc-950 hover:bg-zinc-200"
                >
                  {creating ? <LoaderCircle className="action-spinner mr-2" /> : <Plus className="mr-1 size-4" />}
                  创建并进入
                </Button>
              </div>
            </form>
          </Card>
        </div>
      )}

      {/* 我的素材库弹窗 Dialog */}
      {assetsModalOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="assets-modal-title"
          onClick={() => setAssetsModalOpen(false)}
        >
          <Card
            className="flex flex-col w-full max-w-4xl h-[80vh] border border-white/10 bg-zinc-950 text-zinc-100 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 pb-4 shrink-0">
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-xl bg-white/10 text-white">
                  <FolderArchive className="size-5" />
                </div>
                <div>
                  <CardTitle id="assets-modal-title" className="text-xl font-medium">我的素材库</CardTitle>
                  <p className="text-xs text-zinc-400 mt-0.5">查看您上传的图片参考与 AI 生成的视频/图片资产</p>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setAssetsModalOpen(false)}
              >
                <X className="size-5" />
              </Button>
            </CardHeader>

            {/* 工具栏 */}
            <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3 border-b border-white/5 bg-zinc-900/50 shrink-0">
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant={assetFilter === "all" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setAssetFilter("all")}
                  className={assetFilter === "all" ? "bg-white text-zinc-950" : "text-zinc-400"}
                >
                  全部
                </Button>
                <Button
                  type="button"
                  variant={assetFilter === "image" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setAssetFilter("image")}
                  className={assetFilter === "image" ? "bg-white text-zinc-950" : "text-zinc-400"}
                >
                  <ImageIcon className="size-3.5 mr-1" />图片
                </Button>
                <Button
                  type="button"
                  variant={assetFilter === "video" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setAssetFilter("video")}
                  className={assetFilter === "video" ? "bg-white text-zinc-950" : "text-zinc-400"}
                >
                  <Film className="size-3.5 mr-1" />视频
                </Button>
              </div>

              <div className="flex items-center gap-2">
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 size-4 text-zinc-500" />
                  <Input
                    placeholder="搜索文件名..."
                    value={assetSearch}
                    onChange={(e) => setAssetSearch(e.target.value)}
                    className="pl-8 h-9 w-48 bg-zinc-900 border-white/10 text-xs text-white placeholder:text-zinc-500"
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => void loadUserAssets()}
                  disabled={assetsLoading}
                  aria-label="刷新素材"
                >
                  <RefreshCw className={assetsLoading ? "animate-spin size-4" : "size-4"} />
                </Button>
              </div>
            </div>

            {/* 素材网格列表 */}
            <div className="flex-1 overflow-y-auto p-6">
              {assetsLoading ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="rounded-xl overflow-hidden bg-zinc-900/60 p-2 space-y-2">
                      <Skeleton className="aspect-video w-full rounded-lg" />
                      <Skeleton className="h-4 w-3/4" />
                      <Skeleton className="h-3 w-1/2" />
                    </div>
                  ))}
                </div>
              ) : assets.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center py-16 text-zinc-500">
                  <FolderArchive className="size-12 stroke-[1.2] mb-3 text-zinc-600" />
                  <p className="text-sm">暂无符合条件的素材</p>
                  <p className="text-xs text-zinc-600 mt-1">进入项目工作台后，上传的参考图或生成的视频会自动同步至此</p>
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
                  {assets.map((asset) => (
                    <div
                      key={asset.id}
                      className="group relative rounded-xl border border-white/5 bg-zinc-900/40 p-2.5 transition hover:border-white/20 hover:bg-zinc-900/80"
                    >
                      <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-zinc-950">
                        {asset.kind === "video" ? (
                          <div className="flex size-full items-center justify-center bg-zinc-900 text-zinc-500">
                            <Film className="size-8" />
                          </div>
                        ) : (
                          <img
                            src={asset.url}
                            alt={asset.filename}
                            className="size-full object-cover transition group-hover:scale-105"
                            loading="lazy"
                          />
                        )}
                        <Badge
                          variant="secondary"
                          className="absolute left-2 top-2 bg-black/60 text-[10px] backdrop-blur-xs font-normal"
                        >
                          {asset.kind === "video" ? "视频" : "图片"}
                        </Badge>
                      </div>

                      <div className="mt-2.5 space-y-1">
                        <p className="text-xs font-medium text-zinc-200 truncate" title={asset.filename}>
                          {asset.filename}
                        </p>
                        <div className="flex items-center justify-between text-[11px] text-zinc-500">
                          <span>{formatAssetSize(asset.size)}</span>
                          <span>{formatProjectDate(asset.created_at)}</span>
                        </div>
                      </div>

                      {/* 快捷悬浮操作条 */}
                      <div className="absolute inset-x-2.5 top-2.5 bottom-12 flex items-center justify-center gap-2 rounded-lg bg-black/60 opacity-0 backdrop-blur-xs transition group-hover:opacity-100">
                        <a
                          href={asset.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex size-8 items-center justify-center rounded-lg bg-white/20 text-white hover:bg-white/30"
                          title="在新标签页查看"
                        >
                          <ExternalLink className="size-4" />
                        </a>
                        <a
                          href={asset.url}
                          download={asset.filename}
                          className="flex size-8 items-center justify-center rounded-lg bg-white/20 text-white hover:bg-white/30"
                          title="下载素材"
                        >
                          <Download className="size-4" />
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>
        </div>
      )}
    </main>
  );
}
