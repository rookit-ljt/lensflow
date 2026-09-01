import { Plus, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatDuration } from "@/components/studio/studio-config";
import type { Project } from "@/lib/api";

type ShotRailProps = {
  project: Project;
  selectedShotId?: string;
  open: boolean;
  totalDuration: number;
  onClose: () => void;
  onAddShot: () => void;
  onSelectShot: (shotId: string) => void;
};

export function ShotRail({
  project,
  selectedShotId,
  open,
  totalDuration,
  onClose,
  onAddShot,
  onSelectShot,
}: ShotRailProps) {
  return (
    <aside className={`shot-rail ${open ? "is-open" : ""}`} aria-label="镜头列表">
      <div className="panel-heading">
        <div><span className="kicker">SHOTS</span><h2>镜头</h2></div>
        <div className="panel-heading__actions">
          <Button variant="ghost" size="icon" aria-label="新增镜头" type="button" onClick={onAddShot}><Plus /></Button>
          <Button variant="ghost" size="icon" aria-label="关闭镜头列表" type="button" onClick={onClose}><X /></Button>
        </div>
      </div>
      <ScrollArea className="shot-list-scroll">
        <div className="shot-list">
          {project.shots.map((shot) => (
            <Button
              key={shot.id}
              type="button"
              variant="ghost"
              className={`shot-card shot-card--${shot.id === selectedShotId ? "active" : shot.status}`}
              onClick={() => onSelectShot(shot.id)}
            >
              <span className="shot-card__number">{String(shot.sequence_number).padStart(2, "0")}</span>
              <span className="shot-card__copy"><strong>{shot.title}</strong><small>{shot.duration_seconds}.0 SEC · DB</small></span>
              <span className="shot-card__signal" aria-hidden="true" />
            </Button>
          ))}
        </div>
      </ScrollArea>
      <div className="rail-summary">
        <span>总时长</span>
        <Badge variant="secondary">{project.shots.length} / {formatDuration(totalDuration)}</Badge>
      </div>
    </aside>
  );
}
