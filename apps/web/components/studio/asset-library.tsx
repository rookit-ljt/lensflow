"use client";

import { useMemo, useRef, useState } from "react";
import {
  CircleAlert,
  Download,
  FileImage,
  Film,
  FolderArchive,
  ImagePlus,
  LoaderCircle,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { generationDownloadUrl, type ProjectAsset } from "@/lib/api";

type AssetKindFilter = "all" | "image" | "video";

type AssetLibraryProps = {
  open: boolean;
  assets: ProjectAsset[];
  selectedNodeId?: string | null;
  uploading?: boolean;
  deletingAssetId?: string | null;
  error?: string | null;
  onClose: () => void;
  onUpload: (files: File[]) => void;
  onInsert: (asset: ProjectAsset) => void;
  onDelete: (asset: ProjectAsset) => void;
  onRefresh: () => void;
};

const kindLabels: Record<string, string> = {
  image: "图片",
  video: "视频",
  text: "文本",
};

const roleLabels: Record<string, string> = {
  reference: "上传素材",
  generation: "生成结果",
  last_frame: "视频末帧",
};

function formatAssetSize(size: number): string {
  if (!size) return "云端资源";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function assetDownloadUrl(asset: ProjectAsset): string {
  return asset.source_generation_id
    ? generationDownloadUrl(asset.source_generation_id)
    : asset.url;
}

export function AssetLibrary({
  open,
  assets,
  selectedNodeId,
  uploading = false,
  deletingAssetId,
  error,
  onClose,
  onUpload,
  onInsert,
  onDelete,
  onRefresh,
}: AssetLibraryProps) {
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<AssetKindFilter>("all");
  const [query, setQuery] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const filteredAssets = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return assets.filter((asset) => (
      (kind === "all" || asset.kind === kind)
      && (!normalizedQuery || asset.filename.toLocaleLowerCase().includes(normalizedQuery))
    ));
  }, [assets, kind, query]);

  return (
    <aside className={`asset-library ${open ? "is-open" : ""}`} aria-hidden={!open} aria-label="项目资产库">
      <header className="asset-library__header">
        <div>
          <span className="kicker">PROJECT ASSETS</span>
          <h2><FolderArchive />资产库</h2>
        </div>
        <div className="asset-library__header-actions">
          <Badge variant="outline">{assets.length} 项</Badge>
          <Tooltip>
            <TooltipTrigger render={<Button type="button" variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭资产库" />}>
              <X />
            </TooltipTrigger>
            <TooltipContent>关闭</TooltipContent>
          </Tooltip>
        </div>
      </header>

      <div className="asset-library__toolbar">
        <label className="asset-library__search">
          <Search />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索资产名称" />
        </label>
        <Button type="button" disabled={uploading} onClick={() => uploadInputRef.current?.click()}>
          {uploading ? <LoaderCircle className="asset-library__spinner" /> : <Plus />}
          {uploading ? "上传中" : "上传图片"}
        </Button>
        <input
          ref={uploadInputRef}
          className="asset-library__upload-input"
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          multiple
          tabIndex={-1}
          onChange={(event) => {
            const files = Array.from(event.currentTarget.files ?? []);
            event.currentTarget.value = "";
            if (files.length) onUpload(files);
          }}
        />
      </div>

      <Tabs value={kind} onValueChange={(value) => setKind(value as AssetKindFilter)} className="asset-library__tabs">
        <TabsList>
          <TabsTrigger value="all">全部</TabsTrigger>
          <TabsTrigger value="image">图片</TabsTrigger>
          <TabsTrigger value="video">视频</TabsTrigger>
        </TabsList>
      </Tabs>

      {error ? <div className="asset-library__error"><CircleAlert />{error}</div> : null}

      <ScrollArea className="asset-library__scroll">
        {filteredAssets.length ? (
          <div className="asset-library__grid">
            {filteredAssets.map((asset) => {
              const deleting = deletingAssetId === asset.id;
              const confirming = confirmDeleteId === asset.id;
              return (
                <Card key={asset.id} size="sm" className="asset-card">
                  <div className={`asset-card__preview asset-card__preview--${asset.kind}`}>
                    {asset.kind === "image" ? (
                      <img src={asset.url} alt={asset.filename} loading="lazy" draggable={false} />
                    ) : asset.kind === "video" ? (
                      <video src={asset.url} muted preload="metadata" />
                    ) : (
                      <FileImage />
                    )}
                    <Badge variant="secondary" className="asset-card__kind">
                      {asset.kind === "video" ? <Film /> : <FileImage />}
                      {kindLabels[asset.kind] ?? asset.kind}
                    </Badge>
                  </div>
                  <CardContent className="asset-card__content">
                    <div className="asset-card__title" title={asset.filename}>{asset.filename}</div>
                    <div className="asset-card__meta">
                      <span>{roleLabels[asset.role] ?? asset.role}</span>
                      <span>{formatAssetSize(asset.size)}</span>
                    </div>
                    <div className="asset-card__actions">
                      {asset.kind === "image" ? (
                        <Button
                          type="button"
                          size="sm"
                          disabled={!selectedNodeId}
                          title={selectedNodeId ? "作为参考图插入当前节点" : "请先选择画布节点"}
                          onClick={() => onInsert(asset)}
                        >
                          <ImagePlus />插入节点
                        </Button>
                      ) : null}
                      <Tooltip>
                        <TooltipTrigger render={<Button render={<a href={assetDownloadUrl(asset)} download={asset.filename} />} variant="outline" size="icon-sm" aria-label={`下载 ${asset.filename}`} />}>
                          <Download />
                        </TooltipTrigger>
                        <TooltipContent>下载</TooltipContent>
                      </Tooltip>
                      {confirming ? (
                        <div className="asset-card__confirm-delete">
                          <Button type="button" variant="ghost" size="xs" onClick={() => setConfirmDeleteId(null)}>取消</Button>
                          <Button
                            type="button"
                            variant="destructive"
                            size="xs"
                            disabled={deleting}
                            onClick={() => onDelete(asset)}
                          >
                            {deleting ? <LoaderCircle className="asset-library__spinner" /> : null}确认
                          </Button>
                        </div>
                      ) : (
                        <Tooltip>
                          <TooltipTrigger render={<Button type="button" variant="ghost" size="icon-sm" aria-label={`删除 ${asset.filename}`} onClick={() => setConfirmDeleteId(asset.id)} />}>
                            <Trash2 />
                          </TooltipTrigger>
                          <TooltipContent>删除资产</TooltipContent>
                        </Tooltip>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        ) : (
          <div className="asset-library__empty">
            <FolderArchive />
            <strong>{assets.length ? "没有匹配的资产" : "项目资产库还是空的"}</strong>
            <span>{assets.length ? "调整类型或搜索词再试试" : "上传参考图片，或在画布中生成图片和视频"}</span>
            {!assets.length ? (
              <Button type="button" variant="outline" onClick={() => uploadInputRef.current?.click()}>
                <Plus />上传第一张图片
              </Button>
            ) : (
              <Button type="button" variant="ghost" onClick={() => { setQuery(""); setKind("all"); }}>清除筛选</Button>
            )}
          </div>
        )}
      </ScrollArea>

      <footer className="asset-library__footer">
        <span>{selectedNodeId ? "已选择画布节点，可插入图片资产" : "先选择画布节点，再插入图片资产"}</span>
        <Button type="button" variant="ghost" size="xs" onClick={onRefresh}>刷新</Button>
      </footer>
    </aside>
  );
}
