import {
  Bot,
  Boxes,
  Download,
  Film,
  FolderArchive,
  LayoutDashboard,
  LogOut,
  Map,
  Plus,
  RefreshCw,
  Share2,
  Settings2,
  Sparkles,
  Users,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatDuration, syncLabel } from "@/components/studio/studio-config";
import type { SyncState } from "@/components/studio/studio-types";
import { projectExportUrl, type CurrentUser, type Project, type Shot } from "@/lib/api";

type StudioHeaderProps = {
  currentUser: CurrentUser;
  project: Project | null;
  selectedShot: Shot | null;
  syncState: SyncState;
  error: string | null;
  agentOpen: boolean;
  onSettingsOpenChange: (open: boolean) => void;
  onSelectShot: (shotId: string) => void;
  onAgentOpenChange: (open: boolean) => void;
  onReload: () => void;
  onBackToDashboard: () => void;
  onLogout: () => Promise<void>;
};

export function StudioHeader({
  currentUser,
  project,
  selectedShot,
  syncState,
  error,
  agentOpen,
  onSelectShot,
  onAgentOpenChange,
  onSettingsOpenChange,
  onReload,
  onBackToDashboard,
  onLogout,
}: StudioHeaderProps) {
  return (
    <header className="studio-header">
      <div className="brand-lockup" aria-label="Framefield">
        <Tooltip>
          <TooltipTrigger render={<Button className="dashboard-return" type="button" variant="ghost" size="icon-sm" onClick={onBackToDashboard} aria-label="返回项目首页" />}>
            <LayoutDashboard />
          </TooltipTrigger>
          <TooltipContent>返回项目首页</TooltipContent>
        </Tooltip>
        <span className="brand-mark">S</span>
        <div className="story-lockup">
          <span className="brand-name">{project?.name ?? "Framefield"}</span>
          {project && selectedShot ? (
            <Select value={selectedShot.id} onValueChange={(value) => value && onSelectShot(String(value))}>
              <SelectTrigger size="sm" className="header-shot-switch" aria-label="切换镜头">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="start">
                {project.shots.map((shot) => (
                  <SelectItem key={shot.id} value={shot.id}>
                    {String(shot.sequence_number).padStart(2, "0")} · {shot.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
        </div>
      </div>

      {project ? (
        <Tabs
          value={agentOpen ? "agent" : "canvas"}
          onValueChange={(value) => onAgentOpenChange(value === "agent")}
          className="view-switch"
        >
          <TabsList>
            <TabsTrigger value="canvas"><Map />画布</TabsTrigger>
            <TabsTrigger value="agent"><Bot />Agent</TabsTrigger>
          </TabsList>
        </Tabs>
      ) : <div className="project-crumbs">连接真实项目数据</div>}

      <div className="header-actions">
        <Badge variant="outline" className={`save-state save-state--${syncState}`} title={error ?? syncLabel[syncState]}>
          <i /><span>{syncLabel[syncState]}</span>
        </Badge>
        <Tooltip>
          <TooltipTrigger
            render={<Button className="header-icon-button" type="button" variant="outline" size="icon" onClick={onReload} />}
          >
            <RefreshCw />
          </TooltipTrigger>
          <TooltipContent>重新读取项目与工作流</TooltipContent>
        </Tooltip>
        {project ? (
          <Tooltip>
            <TooltipTrigger
              render={<a className="header-icon-button header-export-link" href={projectExportUrl(project.id)} download={`libtv-project-${project.id}.json`} aria-label="导出项目备份" />}
            >
              <Download />
            </TooltipTrigger>
            <TooltipContent>导出项目备份（JSON）</TooltipContent>
          </Tooltip>
        ) : null}
        <Tooltip>
          <TooltipTrigger render={<Button className="header-icon-button" type="button" variant="outline" size="icon" onClick={() => onSettingsOpenChange(true)} aria-label="模型设置" />}>
            <Settings2 />
          </TooltipTrigger>
          <TooltipContent>配置 LLM Key 与模型</TooltipContent>
        </Tooltip>
        {/* <Button className="header-icon-button" type="button" variant="outline" size="icon" disabled aria-label="分享"><Share2 /></Button> */}
        {/* <Badge variant="outline" className="credit-pill"><Sparkles />100 <strong>开通会员</strong></Badge> */}
        <Button className="agent-button" type="button" variant="outline" onClick={() => onAgentOpenChange(true)}><Bot />Chat Agent</Button>
        <div className="header-user" title={currentUser.email}>
          <span>{currentUser.display_name.slice(0, 1).toUpperCase()}</span>
          <div><strong>{currentUser.display_name}</strong><small>{currentUser.email}</small></div>
        </div>
        <Tooltip>
          <TooltipTrigger render={<Button className="header-icon-button" type="button" variant="ghost" size="icon" aria-label="退出登录" onClick={() => void onLogout()} />}>
            <LogOut />
          </TooltipTrigger>
          <TooltipContent>退出登录</TooltipContent>
        </Tooltip>
      </div>
    </header>
  );
}

type CanvasSideRailProps = {
  onAddNode: () => void;
  onToggleShots: () => void;
  onAddShot: () => void;
  onToggleAssets: () => void;
  onToggleAgent: () => void;
};

export function CanvasSideRail({
  onAddNode,
  onToggleShots,
  onAddShot,
  onToggleAssets,
  onToggleAgent,
}: CanvasSideRailProps) {
  return (
    <nav className="canvas-side-rail" aria-label="画布工具">
      <Tooltip>
        <TooltipTrigger render={<Button className="rail-primary-action" type="button" size="icon-lg" onClick={onAddNode} aria-label="添加空白节点" />}>
          <Plus />
        </TooltipTrigger>
        <TooltipContent side="right">添加空白节点</TooltipContent>
      </Tooltip>
      <Separator />
      <Tooltip>
        <TooltipTrigger render={<Button type="button" variant="ghost" size="icon" onClick={onToggleShots} aria-label="镜头列表" />}>
          <Boxes />
        </TooltipTrigger>
        <TooltipContent side="right">镜头列表</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger render={<Button type="button" variant="ghost" size="icon" onClick={onAddShot} aria-label="新增镜头" />}>
          <Film />
        </TooltipTrigger>
        <TooltipContent side="right">新增镜头</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger render={<Button type="button" variant="ghost" size="icon" disabled aria-label="角色库" />}>
          <Users />
        </TooltipTrigger>
        <TooltipContent side="right">角色库即将接入</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger render={<Button type="button" variant="ghost" size="icon" onClick={onToggleAssets} aria-label="资产库" />}>
          <FolderArchive />
        </TooltipTrigger>
        <TooltipContent side="right">项目资产库</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger render={<Button type="button" variant="ghost" size="icon" onClick={onToggleAgent} aria-label="Chat Agent" />}>
          <Bot />
        </TooltipTrigger>
        <TooltipContent side="right">Chat Agent</TooltipContent>
      </Tooltip>
    </nav>
  );
}

type TimelineStripProps = {
  selectedShot: Shot;
  shots: Shot[];
  totalDuration: number;
};

export function TimelineStrip({ selectedShot, shots, totalDuration }: TimelineStripProps) {
  return (
    <footer className="timeline-strip">
      <span className="timecode">{formatDuration(selectedShot.duration_seconds)}</span>
      <div className="timeline-track">
        {shots.map((shot) => (
          <span
            key={shot.id}
            className={shot.id === selectedShot.id ? "timeline-track__active" : ""}
            style={{ flexGrow: shot.duration_seconds }}
          />
        ))}
      </div>
      <span>{formatDuration(totalDuration)}</span>
    </footer>
  );
}
