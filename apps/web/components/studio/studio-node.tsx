import { createContext, useContext } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Crop, Download, ImageDown, ImageIcon, LoaderCircle, Plus, Video } from "lucide-react";

import { Textarea } from "@/components/ui/textarea";

import { creationMode, stageLabel } from "./studio-config";
import type { StudioFlowNode } from "./studio-types";

type StudioNodeActions = {
  onTextContentChange: (nodeId: string, value: string) => void;
  onExtractLastFrame: (nodeId: string) => void;
  extractingFrameNodeId: string | null;
  onEditImage?: (nodeId: string, imageUrl: string, title: string) => void;
};

export const StudioNodeActionsContext = createContext<StudioNodeActions>({
  onTextContentChange: () => undefined,
  onExtractLastFrame: () => undefined,
  extractingFrameNodeId: null,
  onEditImage: () => undefined,
});

function MediaDownload({ href, kind }: { href?: string; kind: "图片" | "视频" }) {
  if (!href) return null;
  return (
    <a
      className="flow-node__media-action nodrag nowheel"
      href={href}
      aria-label={`下载${kind}`}
      title={`下载${kind}`}
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <Download aria-hidden="true" />
    </a>
  );
}

function ImageActions({
  downloadUrl,
  onEdit,
}: {
  downloadUrl?: string;
  onEdit?: () => void;
}) {
  return (
    <div className="flow-node__media-actions nodrag nowheel">
      {onEdit ? (
        <button
          className="flow-node__media-action flow-node__media-action--edit"
          type="button"
          aria-label="编辑与裁剪图片"
          title="编辑、裁剪与一键抠图"
          onClick={(event) => {
            event.stopPropagation();
            onEdit();
          }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <Crop aria-hidden="true" />
        </button>
      ) : null}
      <MediaDownload href={downloadUrl} kind="图片" />
    </div>
  );
}

function VideoActions({
  downloadUrl,
  extracting,
  onExtract,
}: {
  downloadUrl?: string;
  extracting: boolean;
  onExtract: () => void;
}) {
  return (
    <div className="flow-node__media-actions nodrag nowheel">
      <button
        className="flow-node__media-action flow-node__media-action--frame"
        type="button"
        disabled={extracting}
        aria-label={extracting ? "正在截取视频末帧" : "截取末帧并创建图片节点"}
        title={extracting ? "正在截取末帧" : "截取末帧，创建图片节点"}
        onClick={(event) => {
          event.stopPropagation();
          onExtract();
        }}
        onPointerDown={(event) => event.stopPropagation()}
      >
        {extracting ? <LoaderCircle className="is-spinning" aria-hidden="true" /> : <ImageDown aria-hidden="true" />}
      </button>
      <MediaDownload href={downloadUrl} kind="视频" />
    </div>
  );
}

export function StudioNode({ id, data, selected }: NodeProps<StudioFlowNode>) {
  const {
    onTextContentChange,
    onExtractLastFrame,
    extractingFrameNodeId,
    onEditImage,
  } = useContext(StudioNodeActionsContext);
  const mode = creationMode(data.config);
  const isCreationNode = data.kind === "generator";
  const isImageResult = Boolean(data.imageUrl);
  const isVideoResult = Boolean(data.videoUrl);
  const isMediaResult = isImageResult || isVideoResult;
  const isPortraitImage = isImageResult && (data.imageAspectRatio ?? 16 / 9) < 1;
  return (
    <article
      className={`flow-node flow-node--${data.stage} ${isCreationNode ? "flow-node--creation" : ""} ${isCreationNode && !mode ? "flow-node--blank" : ""} ${isMediaResult ? "flow-node--media-result" : ""} ${isImageResult ? "flow-node--image-result" : ""} ${isVideoResult ? "flow-node--video-result" : ""} ${isPortraitImage ? "flow-node--image-portrait" : ""} ${data.busy ? "is-busy" : ""} ${selected ? "is-selected" : ""}`}
      aria-busy={data.busy || undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flow-node__topline">
        <span className="flow-node__kind">
          {isImageResult ? <ImageIcon aria-hidden="true" /> : null}
          {isVideoResult ? <Video aria-hidden="true" /> : null}
          {isImageResult ? "图片" : isVideoResult ? "视频" : data.eyebrow}
        </span>
        <span className="flow-node__state">{stageLabel[data.stage]}</span>
      </div>
      {isCreationNode && !mode ? (
        <div className="flow-node__blank-body">
          <span aria-hidden="true"><Plus /></span>
          <strong>空白节点</strong>
          <small>选中后配置生成方式</small>
        </div>
      ) : isImageResult ? (
        <div
          className="flow-node__image-frame"
          style={{ aspectRatio: data.imageAspectRatio ?? 16 / 9 }}
          title={data.output}
        >
          <ImageActions
            downloadUrl={data.downloadUrl}
            onEdit={data.imageUrl && onEditImage ? () => onEditImage(id, data.imageUrl!, data.title) : undefined}
          />
          <img
            className="flow-node__image"
            src={data.imageUrl}
            alt={`${data.title}生成结果`}
            draggable={false}
          />
        </div>
      ) : isVideoResult ? (
        <div className="flow-node__video-frame" title={data.output}>
          <VideoActions
            downloadUrl={data.downloadUrl}
            extracting={extractingFrameNodeId === id}
            onExtract={() => onExtractLastFrame(id)}
          />
          <video
            className="flow-node__video nodrag nowheel"
            src={data.videoUrl}
            controls
            playsInline
            preload="metadata"
            aria-label={`${data.title}生成结果`}
            onPointerDown={(event) => event.stopPropagation()}
          />
          <div className="flow-node__media-caption">
            <span>LOCAL H3 OUTPUT</span>
            <strong>{data.output}</strong>
          </div>
        </div>
      ) : (
        <>
          <h3>{data.title}</h3>
          {data.editableText ? (
            <Textarea
              className="flow-node__text-editor nodrag nowheel"
              value={data.detail}
              disabled={data.busy}
              aria-label={`${data.title}内容`}
              onClick={(event) => event.stopPropagation()}
              onPointerDown={(event) => event.stopPropagation()}
              onChange={(event) => onTextContentChange(id, event.target.value)}
            />
          ) : <p>{data.detail}</p>}
          {data.output ? <div className="flow-node__output">{data.output}</div> : null}
        </>
      )}
      {data.busy ? (
        <div className="flow-node__loading" role="status">
          <LoaderCircle />
          <strong>生成中，请稍候</strong>
          <span>模型正在处理内容</span>
        </div>
      ) : null}
      <Handle type="source" position={Position.Right} />
    </article>
  );
}
