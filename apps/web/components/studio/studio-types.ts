import type { Node } from "@xyflow/react";

export type Stage = "done" | "running" | "ready" | "waiting";
export type SyncState = "loading" | "saved" | "saving" | "error";
export type CreationMode = "text" | "image" | "video" | "audio";
export type VideoReferenceMode = "text" | "keyframe" | "ref2va";
export type H3ReferenceRole = "character" | "scene" | "style" | "prop" | "effect";

export type H3ReferenceBinding = {
  nodeId: string;
  order: number;
  role: H3ReferenceRole;
  name: string;
  preserve: string;
  mutable: string;
  exclude: string;
};

export type StudioNodeData = {
  kind: string;
  version: string;
  config: Record<string, unknown>;
  eyebrow: string;
  title: string;
  detail: string;
  stage: Stage;
  output?: string;
  imageUrl?: string;
  imageAspectRatio?: number;
  videoUrl?: string;
  downloadUrl?: string;
  busy?: boolean;
  editableText?: boolean;
};

export type StudioFlowNode = Node<StudioNodeData, "studio">;

export type ContextReference = {
  nodeId: string;
  title: string;
  kind: "text" | "image";
  source: "canvas" | "upload";
  assetId?: string;
  text?: string;
  imageUrl?: string;
};
