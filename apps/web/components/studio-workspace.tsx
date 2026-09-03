"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
} from "@xyflow/react";
import {
  CircleAlert,
  Database,
  Plus,
  RefreshCw,
  Redo2,
  Undo2,
} from "lucide-react";
import { useRouter } from "next/navigation";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type CurrentUser,
  type Generation,
  type ProjectAsset,
  type ProviderCapability,
  type Project,
  type Shot,
  type Workflow,
  type WorkflowWrite,
} from "@/lib/api";

import { NodeComposer } from "@/components/studio/node-composer";
import { AssetLibrary } from "@/components/studio/asset-library";
import { ChatAgent } from "@/components/studio/chat-agent";
import { LlmSettings } from "@/components/studio/llm-settings";
import { ShotRail } from "@/components/studio/shot-rail";
import {
  nodeContextReference,
  presentNode,
  recordToNode,
} from "@/components/studio/node-presentation";
import {
  compileH3Ref2vaPrompt,
  creationMode,
  defaultH3ReferenceBinding,
  demoShots,
  frameNodeSelection,
  h3ReferenceBindings,
  numberConfig,
  textConfig,
  uploadedAssets,
  videoReferenceMode,
} from "@/components/studio/studio-config";
import { edgeTypes } from "@/components/studio/studio-edge";
import {
  CanvasSideRail,
  StudioHeader,
  TimelineStrip,
} from "@/components/studio/studio-chrome";
import { StudioNode, StudioNodeActionsContext } from "@/components/studio/studio-node";
import type {
  ContextReference,
  StudioFlowNode,
  StudioNodeData,
  SyncState,
} from "@/components/studio/studio-types";

const emptyGenerationHistory: Generation[] = [];
const workspaceNodeTypes: NodeTypes = { studio: StudioNode };

function createWorkflowOperationId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `workflow-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function workflowPayload(
  workflow: Workflow,
  nodes: StudioFlowNode[],
  edges: Edge[],
  viewport: { x: number; y: number; zoom: number },
): WorkflowWrite {
  return {
    schema_version: workflow.schema_version,
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.data.kind,
      version: node.data.version,
      position: node.position,
      config: node.data.config,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      source_handle: edge.sourceHandle ?? null,
      target_handle: edge.targetHandle ?? null,
    })),
    viewport,
    base_revision: workflow.revision,
    operation_id: createWorkflowOperationId(),
  };
}

function workflowSnapshot(payload: WorkflowWrite): string {
  const { base_revision: _baseRevision, operation_id: _operationId, ...canvas } = payload;
  return JSON.stringify(canvas);
}

type CanvasHistorySnapshot = {
  nodes: StudioFlowNode[];
  edges: Edge[];
  viewport: { x: number; y: number; zoom: number };
};

function canvasSnapshot(
  nodes: StudioFlowNode[],
  edges: Edge[],
  viewport: { x: number; y: number; zoom: number },
): CanvasHistorySnapshot {
  return {
    nodes: nodes.map((node) => ({
      ...node,
      position: { ...node.position },
      data: { ...node.data, config: { ...node.data.config } },
    })),
    edges: edges.map((edge) => ({ ...edge })),
    viewport: { ...viewport },
  };
}

function canvasSnapshotKey(snapshot: CanvasHistorySnapshot): string {
  return JSON.stringify({
    nodes: snapshot.nodes.map((node) => ({
      id: node.id,
      type: node.type,
      position: node.position,
      data: { kind: node.data.kind, version: node.data.version, config: node.data.config },
    })),
    edges: snapshot.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
    })),
    viewport: snapshot.viewport,
  });
}

function connectionCreatesCycle(edges: Edge[], source: string, target: string): boolean {
  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    const next = adjacency.get(edge.source) ?? [];
    next.push(edge.target);
    adjacency.set(edge.source, next);
  }
  const visited = new Set<string>();
  const pending = [target];
  while (pending.length) {
    const current = pending.pop();
    if (!current || visited.has(current)) continue;
    if (current === source) return true;
    visited.add(current);
    pending.push(...(adjacency.get(current) ?? []));
  }
  return false;
}

type StudioWorkspaceProps = {
  currentUser: CurrentUser;
  projectId: string;
  onLogout: () => Promise<void>;
};

export function StudioWorkspace({ currentUser, projectId, onLogout }: StudioWorkspaceProps) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [syncState, setSyncState] = useState<SyncState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [generations, setGenerations] = useState<Record<string, Generation | undefined>>({});
  const [generationHistory, setGenerationHistory] = useState<Record<string, Generation[]>>({});
  const [providerCapabilities, setProviderCapabilities] = useState<ProviderCapability[]>([]);
  const [projectAssets, setProjectAssets] = useState<ProjectAsset[]>([]);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [workflowReady, setWorkflowReady] = useState(false);
  const [shotRailOpen, setShotRailOpen] = useState(false);
  const [assetLibraryOpen, setAssetLibraryOpen] = useState(false);
  const [assetLibraryUploading, setAssetLibraryUploading] = useState(false);
  const [deletingAssetId, setDeletingAssetId] = useState<string | null>(null);
  const [assetLibraryError, setAssetLibraryError] = useState<string | null>(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [shotRunning, setShotRunning] = useState(false);
  const [pendingNodeId, setPendingNodeId] = useState<string | null>(null);
  const [uploadingNodeId, setUploadingNodeId] = useState<string | null>(null);
  const [extractingFrameNodeId, setExtractingFrameNodeId] = useState<string | null>(null);
  const [canvasViewport, setCanvasViewport] = useState({ x: 30, y: 90, zoom: 0.78 });
  const [flowSize, setFlowSize] = useState({ width: 0, height: 0 });
  const [historyState, setHistoryState] = useState({ canUndo: false, canRedo: false });
  const [nodes, setNodes, onNodesChange] = useNodesState<StudioFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const flowWrapRef = useRef<HTMLDivElement>(null);
  const savedWorkflowSnapshotRef = useRef<string | null>(null);
  const latestWorkflowSnapshotRef = useRef<string | null>(null);
  const saveRequestIdRef = useRef(0);
  const saveScheduleIdRef = useRef(0);
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const workflowRevisionRef = useRef(0);
  const saveEpochRef = useRef(0);
  const canvasHistoryRef = useRef<CanvasHistorySnapshot[]>([]);
  const canvasHistoryIndexRef = useRef(-1);
  const historyShotIdRef = useRef<string | null>(null);
  const applyingHistoryRef = useRef<CanvasHistorySnapshot | null>(null);

  const resetCanvasHistory = useCallback(() => {
    canvasHistoryRef.current = [];
    canvasHistoryIndexRef.current = -1;
    historyShotIdRef.current = null;
    applyingHistoryRef.current = null;
    setHistoryState({ canUndo: false, canRedo: false });
  }, []);

  const persistWorkflow = useCallback((shotId: string, payload: WorkflowWrite) => {
    const epoch = saveEpochRef.current;
    const operation = saveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        if (epoch !== saveEpochRef.current) return null;
        return api.saveWorkflow(shotId, {
          ...payload,
          // Saves are serialized locally. Rebase queued drafts onto the revision
          // committed by the previous request while preserving each operation id.
          base_revision: workflowRevisionRef.current,
        });
      })
      .then((saved) => {
        if (!saved || epoch !== saveEpochRef.current) return null;
        workflowRevisionRef.current = saved.revision;
        return saved;
      });
    saveQueueRef.current = operation.then(() => undefined, () => undefined);
    return operation;
  }, []);

  useEffect(() => {
    if (workflow) workflowRevisionRef.current = workflow.revision;
  }, [workflow]);

  const loadWorkspace = useCallback(async () => {
    setSyncState("loading");
    setError(null);
    try {
      const detail = await api.getProject(projectId);
      setProject(detail);
      setSelectedShotId((current) => (
        current && detail.shots.some((shot) => shot.id === current)
          ? current
          : detail.shots[0]?.id ?? null
      ));
      setSyncState("saved");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法连接 API");
      setSyncState("error");
    }
  }, [projectId]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  // A brand-new project starts as an Agent-first workspace. Keep the canvas
  // hidden until the user has an idea to work on and the Agent creates the
  // first shot.
  useEffect(() => {
    if (project && project.shots.length === 0) {
      setAgentOpen(true);
    }
  }, [project]);

  const refreshProjectAssets = useCallback(async () => {
    try {
      const assets = await api.listAssets(projectId);
      setProjectAssets(assets);
      setAssetLibraryError(null);
    } catch (cause) {
      setAssetLibraryError(cause instanceof Error ? cause.message : "资产库读取失败");
    }
  }, [projectId]);

  useEffect(() => {
    setProjectAssets([]);
    void refreshProjectAssets();
  }, [refreshProjectAssets]);

  useEffect(() => {
    void api.listProviders()
      .then(setProviderCapabilities)
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "Provider 状态读取失败");
        setSyncState("error");
      });
  }, []);

  const selectedShot = useMemo(
    () => project?.shots.find((shot) => shot.id === selectedShotId) ?? project?.shots[0] ?? null,
    [project, selectedShotId],
  );
  const activeShotId = selectedShot?.id;
  const configuredImageProvider = providerCapabilities.find(
    (provider) => provider.kind === "image" && provider.id !== "mock" && provider.configured,
  );
  const configuredTextProvider = providerCapabilities.find(
    (provider) => provider.kind === "text" && provider.id !== "mock" && provider.configured,
  );
  const configuredVideoProvider = providerCapabilities.find(
    (provider) => provider.kind === "video" && provider.id !== "mock" && provider.configured,
  );
  const selectedGeneration = activeShotId ? generations[activeShotId] : undefined;
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? nodes[0];
  const canvasCenter = useMemo(() => {
    if (!flowSize.width || !flowSize.height) return undefined;
    return {
      x: (flowSize.width / 2 - canvasViewport.x) / canvasViewport.zoom,
      y: (flowSize.height / 2 - canvasViewport.y) / canvasViewport.zoom,
    };
  }, [canvasViewport, flowSize]);
  const shotGenerationHistory = activeShotId
    ? generationHistory[activeShotId] ?? emptyGenerationHistory
    : emptyGenerationHistory;
  const selectedNodeGeneration = selectedNodeId
    ? (selectedGeneration?.node_id === selectedNodeId
      ? selectedGeneration
      : shotGenerationHistory.find((item) => item.node_id === selectedNodeId))
    : undefined;
  const selectedContexts = useMemo(() => {
    if (!selectedNodeId || !selectedShot) return [];
    const history = shotGenerationHistory;
    const sourceIds = edges
      .filter((edge) => edge.target === selectedNodeId)
      .map((edge) => edge.source);
    const canvasContexts = sourceIds
      .map((sourceId) => nodes.find((node) => node.id === sourceId))
      .filter((node): node is StudioFlowNode => Boolean(node))
      .map((node) => nodeContextReference(node, selectedShot, history))
      .filter((context): context is ContextReference => Boolean(context));
    const uploadContexts: ContextReference[] = uploadedAssets(selectedNode.data.config).map((asset) => ({
      nodeId: `upload:${asset.id}`,
      assetId: asset.id,
      title: asset.filename,
      kind: "image",
      source: "upload",
      imageUrl: asset.url,
    }));
    return [...canvasContexts, ...uploadContexts];
  }, [edges, nodes, selectedNode, selectedNodeId, selectedShot, shotGenerationHistory]);
  const runningGenerationNodeId = selectedGeneration?.node_id
    && ["queued", "running"].includes(selectedGeneration.status)
    ? selectedGeneration.node_id
    : null;
  const busyNodeId = pendingNodeId ?? runningGenerationNodeId;
  const selectedNodeBusy = Boolean(selectedNodeId && busyNodeId === selectedNodeId);
  const updateNodeTextContent = useCallback((nodeId: string, text_content: string) => {
    setNodes((current) => current.map((node) => {
      if (node.id !== nodeId) return node;
      const config = { ...node.data.config, text_content };
      return {
        ...node,
        data: {
          ...node.data,
          config,
          detail: text_content,
          stage: "done",
          output: creationMode(config) === "text"
            ? `${textConfig(config, "model", "默认模型")} · ${text_content.length} 字`
            : node.data.output,
        },
      };
    }));
  }, [setNodes]);
  const extractLastFrameToImageNode = useCallback(async (sourceNodeId: string) => {
    if (!selectedShot || extractingFrameNodeId) return;
    const sourceNode = nodes.find((node) => node.id === sourceNodeId);
    const sourceGeneration = shotGenerationHistory.find((item) => (
      item.node_id === sourceNodeId
      && item.kind === "video"
      && item.status === "succeeded"
      && item.output_url
    ));
    if (!sourceNode || !sourceGeneration) {
      setError("当前视频节点还没有可截取的生成结果");
      return;
    }

    setExtractingFrameNodeId(sourceNodeId);
    setError(null);
    try {
      const asset = await api.extractGenerationLastFrame(sourceGeneration.id);
      const id = crypto.randomUUID();
      const width = numberConfig(sourceNode.data.config, "width", 16);
      const height = numberConfig(sourceNode.data.config, "height", 9);
      const aspectRatio = width > 0 && height > 0 ? width / height : 16 / 9;
      const preferredImageProvider = providerCapabilities.find((provider) => (
        provider.kind === "image"
        && provider.configured
        && (provider.id === "qwen" || provider.id === "google_genai")
      )) ?? configuredImageProvider;
      const config = {
        node_id: id,
        mode: "image",
        title: "视频末帧",
        prompt: "",
        provider: preferredImageProvider?.id ?? "mock",
        model: preferredImageProvider?.model ?? "mock-image",
        aspect_ratio: Math.abs(aspectRatio - 1) < 0.05 ? "1:1" : aspectRatio < 1 ? "9:16" : "16:9",
        resolution: "2K",
        quality: "标准",
        count: 1,
        seed: -1,
        uploaded_assets: [asset],
        source_image_url: asset.url,
        source_image_aspect_ratio: aspectRatio,
        source_generation_id: sourceGeneration.id,
      };
      const presentation = presentNode("generator", config, selectedShot);
      setNodes((current) => [
        ...current,
        {
          id,
          type: "studio",
          position: {
            x: sourceNode.position.x + (sourceNode.measured?.width ?? 480) + 110,
            y: sourceNode.position.y + 30,
          },
          data: { kind: "generator", version: "1.0", config, ...presentation },
        },
      ]);
      setEdges((current) => addEdge({
        id: crypto.randomUUID(),
        type: "studio",
        source: sourceNodeId,
        target: id,
      }, current));
      setSelectedNodeId(id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "视频末帧截取失败");
      setSyncState("error");
    } finally {
      setExtractingFrameNodeId((current) => current === sourceNodeId ? null : current);
    }
  }, [configuredImageProvider, extractingFrameNodeId, nodes, providerCapabilities, selectedShot, setEdges, setNodes, shotGenerationHistory]);
  const studioNodeActions = useMemo(() => ({
    onTextContentChange: updateNodeTextContent,
    onExtractLastFrame: (nodeId: string) => void extractLastFrameToImageNode(nodeId),
    extractingFrameNodeId,
  }), [extractLastFrameToImageNode, extractingFrameNodeId, updateNodeTextContent]);
  const editableNodeSignature = useMemo(
    () => nodes.map((node) => `${node.id}:${node.data.kind}:${creationMode(node.data.config) ?? "none"}`).join("|"),
    [nodes],
  );

  useEffect(() => {
    setNodes((current) => {
      let changed = false;
      const next = current.map((node) => {
        const busy = node.id === busyNodeId;
        const editableText = node.data.kind === "shot"
          || (node.data.kind === "generator" && creationMode(node.data.config) === "text");
        const deletable = busy ? false : !["shot", "prompt"].includes(node.data.kind);
        if (
          node.draggable === !busy
          && node.connectable === !busy
          && node.selectable === !busy
          && node.deletable === deletable
          && node.data.busy === busy
          && node.data.editableText === editableText
        ) return node;
        changed = true;
        return {
          ...node,
          draggable: !busy,
          connectable: !busy,
          selectable: !busy,
          deletable,
          data: { ...node.data, busy, editableText },
        };
      });
      return changed ? next : current;
    });
  }, [busyNodeId, editableNodeSignature, setNodes]);
  const composerStyle = useMemo(() => {
    if (!selectedNodeId || !selectedNode || selectedNode.data.kind !== "generator") return undefined;
    const nodeHeight = selectedNode.measured?.height ?? 250;
    const anchorX = selectedNode.position.x * canvasViewport.zoom + canvasViewport.x;
    const anchorY = (selectedNode.position.y + nodeHeight) * canvasViewport.zoom + canvasViewport.y + 18;
    return {
      "--composer-anchor-x": `${anchorX}px`,
      "--composer-anchor-y": `${anchorY}px`,
    } as CSSProperties;
  }, [canvasViewport, selectedNode, selectedNodeId]);
  const activePrompt = selectedNode?.data.kind === "generator"
    ? textConfig(selectedNode.data.config, "prompt", "")
    : selectedShot?.visual_prompt ?? "";
  const totalDuration = project?.shots.reduce((total, shot) => total + shot.duration_seconds, 0) ?? 0;

  useEffect(() => {
    saveEpochRef.current += 1;
    saveQueueRef.current = Promise.resolve();
    resetCanvasHistory();
    if (!activeShotId || !selectedShot) {
      savedWorkflowSnapshotRef.current = null;
      latestWorkflowSnapshotRef.current = null;
      setWorkflow(null);
      setWorkflowReady(false);
      setNodes([]);
      setEdges([]);
      return;
    }
    let cancelled = false;
    setWorkflowReady(false);
    setSyncState("loading");
    void api.getWorkflow(activeShotId)
      .then((loaded) => {
        if (cancelled) return;
        const loadedNodes = loaded.nodes.map((node) => recordToNode(node, selectedShot));
        const loadedEdges = loaded.edges.map((edge) => ({
          id: edge.id,
          type: "studio",
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.source_handle,
          targetHandle: edge.target_handle,
        }));
        const snapshot = workflowSnapshot(
          workflowPayload(loaded, loadedNodes, loadedEdges, loaded.viewport),
        );
        savedWorkflowSnapshotRef.current = snapshot;
        latestWorkflowSnapshotRef.current = snapshot;
        workflowRevisionRef.current = loaded.revision;
        setWorkflow(loaded);
        setCanvasViewport(loaded.viewport);
        setNodes(loadedNodes);
        setEdges(loadedEdges);
        setSelectedNodeId(null);
        setWorkflowReady(true);
        setSyncState("saved");
      })
      .catch((cause) => {
        if (cancelled) return;
        setError(cause instanceof Error ? cause.message : "工作流读取失败");
        setSyncState("error");
      });
    return () => { cancelled = true; };
  }, [activeShotId, resetCanvasHistory, setEdges, setNodes]);

  useEffect(() => {
    if (!activeShotId || !workflowReady) return;
    const snapshot = canvasSnapshot(nodes, edges, canvasViewport);
    const snapshotKey = canvasSnapshotKey(snapshot);
    const pendingRestore = applyingHistoryRef.current;
    if (pendingRestore) {
      if (canvasSnapshotKey(pendingRestore) === snapshotKey) {
        applyingHistoryRef.current = null;
      }
      return;
    }
    if (historyShotIdRef.current !== activeShotId) {
      canvasHistoryRef.current = [snapshot];
      canvasHistoryIndexRef.current = 0;
      historyShotIdRef.current = activeShotId;
      setHistoryState({ canUndo: false, canRedo: false });
      return;
    }
    const current = canvasHistoryRef.current[canvasHistoryIndexRef.current];
    if (current && canvasSnapshotKey(current) === snapshotKey) return;
    const next = canvasHistoryRef.current
      .slice(0, canvasHistoryIndexRef.current + 1)
      .concat(snapshot)
      .slice(-40);
    canvasHistoryRef.current = next;
    canvasHistoryIndexRef.current = next.length - 1;
    setHistoryState({ canUndo: next.length > 1, canRedo: false });
  }, [activeShotId, canvasViewport, edges, nodes, workflowReady]);

  const restoreCanvasHistory = useCallback((direction: -1 | 1) => {
    const targetIndex = canvasHistoryIndexRef.current + direction;
    const target = canvasHistoryRef.current[targetIndex];
    if (!target) return;
    canvasHistoryIndexRef.current = targetIndex;
    applyingHistoryRef.current = target;
    setNodes(target.nodes);
    setEdges(target.edges);
    setCanvasViewport(target.viewport);
    setSelectedNodeId((current) => target.nodes.some((node) => node.id === current) ? current : null);
    setHistoryState({
      canUndo: targetIndex > 0,
      canRedo: targetIndex < canvasHistoryRef.current.length - 1,
    });
  }, [setEdges, setNodes]);

  useEffect(() => {
    const element = flowWrapRef.current;
    if (!element) return;
    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setFlowSize({ width: rect.width, height: rect.height });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [activeShotId, workflowReady]);

  const reloadActiveCanvas = useCallback(async () => {
    if (!selectedShot) return;
    // Any debounced draft captured before the Agent approval is obsolete.
    // The committed workflow returned below becomes the new save baseline.
    saveScheduleIdRef.current += 1;
    saveRequestIdRef.current += 1;
    saveEpochRef.current += 1;
    saveQueueRef.current = Promise.resolve();
    resetCanvasHistory();
    setWorkflowReady(false);
    setSyncState("loading");
    try {
      const [loaded, generationItems] = await Promise.all([
        api.getWorkflow(selectedShot.id),
        api.listGenerations(selectedShot.id),
      ]);
      const loadedNodes = loaded.nodes.map((node) => recordToNode(node, selectedShot));
      const loadedEdges = loaded.edges.map((edge) => ({
        id: edge.id,
        type: "studio",
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.source_handle,
        targetHandle: edge.target_handle,
      }));
      const snapshot = workflowSnapshot(
        workflowPayload(loaded, loadedNodes, loadedEdges, loaded.viewport),
      );
      savedWorkflowSnapshotRef.current = snapshot;
      latestWorkflowSnapshotRef.current = snapshot;
      workflowRevisionRef.current = loaded.revision;
      setWorkflow(loaded);
      setCanvasViewport(loaded.viewport);
      setNodes(loadedNodes);
      setEdges(loadedEdges);
      setGenerationHistory((current) => ({
        ...current,
        [selectedShot.id]: generationItems,
      }));
      setGenerations((current) => ({
        ...current,
        [selectedShot.id]: generationItems[0],
      }));
      setSelectedNodeId(null);
      setWorkflowReady(true);
      setSyncState("saved");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Agent 已应用变更，但画布刷新失败");
      setSyncState("error");
    }
  }, [resetCanvasHistory, selectedShot, setEdges, setNodes]);

  useEffect(() => {
    if (!selectedShot || !workflowReady) return;
    setNodes((current) => current.map((node) => {
      const nodeGeneration = node.data.kind === "generator"
        ? shotGenerationHistory.find((item) => item.node_id === node.id)
        : undefined;
      return {
        ...node,
        data: {
          ...node.data,
          ...presentNode(node.data.kind, node.data.config, selectedShot, nodeGeneration),
        },
      };
    }));
    setEdges((current) => current.map((edge) => ({
      ...edge,
      animated: selectedGeneration?.status === "running" || selectedGeneration?.status === "queued",
    })));
  }, [selectedGeneration, selectedShot, setEdges, setNodes, shotGenerationHistory, workflowReady]);

  useEffect(() => {
    if (
      selectedGeneration?.kind !== "text"
      || selectedGeneration.status !== "succeeded"
      || !selectedGeneration.node_id
      || !selectedGeneration.output_text
    ) return;
    const outputText = selectedGeneration.output_text;
    setNodes((current) => current.map((node) => {
      if (node.id !== selectedGeneration.node_id) return node;
      if (textConfig(node.data.config, "text_content", "") === outputText) return node;
      const config = { ...node.data.config, text_content: outputText };
      return {
        ...node,
        data: {
          ...node.data,
          config,
          detail: outputText,
          stage: "done",
          output: `${selectedGeneration.model || "默认模型"} · ${outputText.length} 字`,
        },
      };
    }));
  }, [selectedGeneration, setNodes]);

  useEffect(() => {
    if (!activeShotId || !workflow || !workflowReady) return;
    const payload = workflowPayload(workflow, nodes, edges, canvasViewport);
    const snapshot = workflowSnapshot(payload);
    latestWorkflowSnapshotRef.current = snapshot;
    if (snapshot === savedWorkflowSnapshotRef.current) return;

    setSyncState("saving");
    const scheduleId = ++saveScheduleIdRef.current;
    const timer = window.setTimeout(() => {
      if (scheduleId !== saveScheduleIdRef.current) return;
      const requestId = ++saveRequestIdRef.current;
      void persistWorkflow(activeShotId, payload).then((saved) => {
        if (!saved) return;
        savedWorkflowSnapshotRef.current = snapshot;
        if (
          requestId === saveRequestIdRef.current
          && latestWorkflowSnapshotRef.current === snapshot
        ) {
          setWorkflow(saved);
          setSyncState("saved");
        }
      }).catch((cause) => {
        if (requestId === saveRequestIdRef.current) {
          setError(cause instanceof Error ? cause.message : "画布保存失败");
          setSyncState("error");
        }
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [activeShotId, canvasViewport, edges, nodes, persistWorkflow, workflow, workflowReady]);

  useEffect(() => {
    if (!activeShotId) return;
    let cancelled = false;
    void api.listGenerations(activeShotId)
      .then((items) => {
        if (!cancelled) {
          setGenerationHistory((current) => ({ ...current, [activeShotId]: items }));
          setGenerations((current) => ({ ...current, [activeShotId]: items[0] }));
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "任务记录读取失败");
          setSyncState("error");
        }
      });
    return () => { cancelled = true; };
  }, [activeShotId]);

  useEffect(() => {
    if (!selectedGeneration || !["queued", "running"].includes(selectedGeneration.status)) return;
    const timer = window.setInterval(() => {
      void api.getGeneration(selectedGeneration.id).then((generation) => {
        setGenerations((current) => ({ ...current, [generation.shot_id]: generation }));
        setGenerationHistory((current) => ({
          ...current,
          [generation.shot_id]: [
            generation,
            ...(current[generation.shot_id] ?? []).filter((item) => item.id !== generation.id),
          ],
        }));
        if (generation.status === "succeeded" || generation.status === "failed") {
          void loadWorkspace();
          if (generation.status === "succeeded") void refreshProjectAssets();
        }
      }).catch((cause) => {
        setError(cause instanceof Error ? cause.message : "生成任务状态读取失败");
      });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [loadWorkspace, refreshProjectAssets, selectedGeneration]);

  const replaceShot = useCallback((updatedShot: Shot) => {
    setProject((current) => current
      ? { ...current, shots: current.shots.map((shot) => shot.id === updatedShot.id ? updatedShot : shot) }
      : current);
  }, []);

  const createDemoProject = useCallback(async () => {
    setSyncState("saving");
    setError(null);
    try {
      const created = await api.createProject({
        name: "沿海失踪案",
        description: "第一集 · 潮汐线",
      });
      for (const [index, shot] of demoShots.entries()) {
        await api.createShot(created.id, { ...shot, sequence_number: index + 1 });
      }
      const detail = await api.getProject(created.id);
      setProject(detail);
      setSelectedShotId(detail.shots[0]?.id ?? null);
      setSyncState("saved");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "示例项目创建失败");
      setSyncState("error");
    }
  }, []);

  const addShot = useCallback(async () => {
    if (!project) return;
    setSyncState("saving");
    try {
      const sequence = project.shots.length + 1;
      const shot = await api.createShot(project.id, {
        sequence_number: sequence,
        title: `未命名镜头 ${sequence}`,
        description: "填写这一镜的叙事动作。",
        duration_seconds: 5,
      });
      setProject((current) => current ? { ...current, shots: [...current.shots, shot] } : current);
      setSelectedShotId(shot.id);
      setSelectedNodeId(null);
      setSyncState("saved");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "新增镜头失败");
      setSyncState("error");
    }
  }, [project]);

  const ensureShotForAgent = useCallback(async (prompt: string) => {
    if (!project) throw new Error("项目尚未加载");
    const existing = project.shots[0];
    if (existing) return existing;
    setSyncState("saving");
    try {
      const shot = await api.createShot(project.id, {
        sequence_number: 1,
        title: "第一个镜头",
        description: "由 Chat Agent 根据创意生成。",
        visual_prompt: prompt.slice(0, 12000),
        duration_seconds: 5,
      });
      // Materialize an empty workflow so the first Agent canvas plan does not
      // reintroduce the legacy shot/prompt/generator starter nodes.
      await api.getWorkflow(shot.id, { empty: true });
      setProject((current) => current ? { ...current, shots: [shot, ...current.shots] } : current);
      setSelectedShotId(shot.id);
      setSelectedNodeId(null);
      setSyncState("saved");
      return shot;
    } catch (cause) {
      setSyncState("error");
      throw cause;
    }
  }, [project]);

  const executeGeneration = useCallback(async () => {
    const basePrompt = selectedNode?.data.kind === "generator"
      ? textConfig(selectedNode.data.config, "prompt", "").trim()
      : selectedShot?.visual_prompt.trim() ?? "";
    const mode = selectedNode?.data.kind === "generator" ? creationMode(selectedNode.data.config) : null;
    const selectedNodeConfig = selectedNode?.data.config ?? {};
    const referenceMode = videoReferenceMode(selectedNodeConfig);
    const imageContexts = selectedContexts.filter((context) => context.kind === "image" && context.imageUrl);
    const availableContextsByNodeId = new Map(imageContexts.map((context) => [context.nodeId, context]));
    const storedBindings = h3ReferenceBindings(selectedNodeConfig);
    const storedNodeIds = new Set(storedBindings.map((binding) => binding.nodeId));
    const referenceBindings = [
      ...storedBindings.filter((binding) => availableContextsByNodeId.has(binding.nodeId)),
      ...imageContexts
        .filter((context) => !storedNodeIds.has(context.nodeId))
        .map((context, index) => defaultH3ReferenceBinding(
          context.nodeId,
          storedBindings.length + index + 1,
          context.title,
        )),
    ].slice(0, 4).map((binding, index) => ({ ...binding, order: index + 1 }));
    const prompt = mode === "video" && referenceMode === "ref2va"
      ? compileH3Ref2vaPrompt(
          textConfig(selectedNodeConfig, "intent_prompt", basePrompt),
          referenceBindings,
          textConfig(selectedNodeConfig, "camera_motion", "自动"),
        )
      : basePrompt;
    if (!selectedShot || !prompt || pendingNodeId || runningGenerationNodeId) return;
    if (mode === "video" && referenceMode === "ref2va" && referenceBindings.length === 0) {
      setError("H3 全参考模式至少需要 1 张图片");
      return;
    }
    if (mode === "video" && referenceMode === "ref2va" && prompt.length > 8000) {
      setError(`编译后的 H3 Prompt 为 ${prompt.length} 字，超过 8000 字限制`);
      return;
    }
    const targetNodeId = selectedNode?.data.kind === "generator" ? selectedNode.id : null;
    setPendingNodeId(targetNodeId);
    setSyncState("saving");
    setError(null);
    try {
      const contextSourceNodeIds = edges
        .filter((edge) => edge.target === targetNodeId)
        .map((edge) => edge.source);
      if (workflow) {
        // Invalidate any debounced snapshot captured before this explicit execution save.
        // Otherwise the older timer can arrive later and remove a newly-created node.
        saveScheduleIdRef.current += 1;
        const payload = workflowPayload(workflow, nodes, edges, canvasViewport);
        const saved = await persistWorkflow(selectedShot.id, payload);
        if (!saved) return;
        const snapshot = workflowSnapshot(payload);
        savedWorkflowSnapshotRef.current = snapshot;
        latestWorkflowSnapshotRef.current = snapshot;
        setWorkflow(saved);
      }
      if (mode !== "text" && prompt !== selectedShot.visual_prompt) {
        replaceShot(await api.updateShot(selectedShot.id, { visual_prompt: prompt }));
      }
      const preset = selectedNode?.data.kind === "generator"
        ? textConfig(selectedNode.data.config, "model", "")
        : "";
      const selectedProviderId = selectedNode?.data.kind === "generator"
        ? textConfig(selectedNode.data.config, "provider", "")
        : "";
      const selectedCapability = providerCapabilities.find((provider) => (
        provider.kind === mode && provider.id === selectedProviderId
      ));
      const effectivePreset = mode === "image"
        && selectedCapability?.id === "qwen"
        && selectedContexts.some((context) => context.kind === "image")
        && ["qwen-image-plus", "qwen-image"].includes(preset)
        ? "qwen-image-2.0-pro"
        : preset;
      const outputLength = textConfig(selectedNode?.data.config ?? {}, "output_length", "中等");
      const selectedUploadedAssets = uploadedAssets(selectedNodeConfig);
      const imageContextNodeIds = selectedContexts
        .filter((context) => context.kind === "image" && context.imageUrl)
        .map((context) => context.nodeId);
      const firstFrameNodeId = frameNodeSelection(
        selectedNodeConfig,
        "first_frame_node_id",
        "",
        imageContextNodeIds,
      );
      const lastFrameNodeId = frameNodeSelection(
        selectedNodeConfig,
        "last_frame_node_id",
        "",
        imageContextNodeIds,
      );
      const generationPayload: Parameters<typeof api.createGeneration>[1] = mode === "text" ? {
        provider: selectedCapability?.id ?? configuredTextProvider?.id ?? "mock",
        kind: "text",
        node_id: selectedNode?.id,
        prompt,
        model: preset || selectedCapability?.model || configuredTextProvider?.model,
        temperature: numberConfig(selectedNode?.data.config ?? {}, "temperature", 0.7),
        max_tokens: outputLength === "简短" ? 1200 : outputLength === "详细" ? 4000 : 2400,
        parameters: { context_source_node_ids: contextSourceNodeIds },
      } : mode === "image" ? {
        provider: selectedCapability?.id ?? configuredImageProvider?.id ?? "mock",
        kind: "image",
        node_id: selectedNode?.id,
        prompt,
        model: effectivePreset || selectedCapability?.model || configuredImageProvider?.model,
        parameters: {
          size: (effectivePreset || selectedCapability?.model || configuredImageProvider?.model) === "dall-e-2"
            ? "1024x1024"
            : textConfig(selectedNode?.data.config ?? {}, "resolution", "2K"),
          aspect_ratio: textConfig(selectedNode?.data.config ?? {}, "aspect_ratio", "16:9"),
          count: numberConfig(selectedNode?.data.config ?? {}, "count", 1),
          seed: numberConfig(selectedNode?.data.config ?? {}, "seed", -1),
          negative_prompt: textConfig(selectedNode?.data.config ?? {}, "negative_prompt", ""),
          prompt_extend: true,
          context_source_node_ids: contextSourceNodeIds,
          uploaded_assets: selectedUploadedAssets,
        },
      } : {
        provider: selectedCapability?.id ?? configuredVideoProvider?.id ?? "mock",
        kind: "video",
        node_id: selectedNode?.id,
        prompt,
        model: preset || selectedCapability?.model || configuredVideoProvider?.model,
        parameters: {
          preset: textConfig(selectedNode?.data.config ?? {}, "preset", "custom"),
          width: numberConfig(selectedNode?.data.config ?? {}, "width", 256),
          height: numberConfig(selectedNode?.data.config ?? {}, "height", 256),
          duration_seconds: numberConfig(selectedNode?.data.config ?? {}, "duration_seconds", 1),
          steps: numberConfig(selectedNode?.data.config ?? {}, "steps", 4),
          seed: numberConfig(selectedNode?.data.config ?? {}, "seed", 42),
          camera_motion: textConfig(selectedNode?.data.config ?? {}, "camera_motion", "自动"),
          output_name: `ai-video-studio-${selectedNode?.id.slice(0, 8) ?? "video"}`,
          video_reference_mode: referenceMode,
          first_frame_node_id: referenceMode === "keyframe" ? firstFrameNodeId : "",
          last_frame_node_id: referenceMode === "keyframe" ? lastFrameNodeId : "",
          reference_image_node_ids: referenceMode === "ref2va"
            ? referenceBindings.map((binding) => binding.nodeId)
            : [],
          reference_bindings: referenceMode === "ref2va"
            ? referenceBindings.map((binding) => ({
                node_id: binding.nodeId,
                order: binding.order,
                role: binding.role,
                name: binding.name,
                preserve: binding.preserve,
                mutable: binding.mutable,
                exclude: binding.exclude,
              }))
            : [],
          prompt_schema: referenceMode === "ref2va" ? "h3_ref2va_v1" : null,
          intent_prompt: referenceMode === "ref2va"
            ? textConfig(selectedNodeConfig, "intent_prompt", basePrompt)
            : null,
          context_source_node_ids: contextSourceNodeIds,
          uploaded_assets: selectedUploadedAssets,
        },
      };
      const generation = await api.createGeneration(selectedShot.id, generationPayload);
      setGenerations((current) => ({ ...current, [selectedShot.id]: generation }));
      setGenerationHistory((current) => ({
        ...current,
        [selectedShot.id]: [
          generation,
          ...(current[selectedShot.id] ?? []).filter((item) => item.id !== generation.id),
        ],
      }));
      setSyncState("saved");
      if (generation.status === "succeeded" || generation.status === "failed") {
        await loadWorkspace();
        if (generation.status === "succeeded") await refreshProjectAssets();
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "任务创建失败");
      setSyncState("error");
    } finally {
      setPendingNodeId((current) => current === targetNodeId ? null : current);
    }
  }, [canvasViewport, configuredImageProvider, configuredTextProvider, configuredVideoProvider, edges, loadWorkspace, nodes, pendingNodeId, persistWorkflow, providerCapabilities, refreshProjectAssets, replaceShot, runningGenerationNodeId, selectedContexts, selectedNode, selectedShot, workflow]);

  const retrySelectedGeneration = useCallback(async () => {
    if (!selectedNodeGeneration || selectedNodeGeneration.status !== "failed") return;
    setError(null);
    setSyncState("saving");
    try {
      const retried = await api.retryGeneration(selectedNodeGeneration.id);
      setGenerations((current) => ({ ...current, [retried.shot_id]: retried }));
      setGenerationHistory((current) => ({
        ...current,
        [retried.shot_id]: [
          retried,
          ...(current[retried.shot_id] ?? []).filter((item) => item.id !== retried.id),
        ],
      }));
      setSyncState("saved");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "生成任务重试失败");
      setSyncState("error");
    }
  }, [selectedNodeGeneration]);

  const runCurrentShot = useCallback(async () => {
    if (!selectedShot || shotRunning) return;
    setShotRunning(true);
    setError(null);
    try {
      const results = await api.runShot(selectedShot.id);
      setGenerationHistory((current) => ({
        ...current,
        [selectedShot.id]: [
          ...results,
          ...(current[selectedShot.id] ?? []).filter((item) => !results.some((result) => result.id === item.id)),
        ],
      }));
      const latest = results[results.length - 1];
      if (latest) setGenerations((current) => ({ ...current, [selectedShot.id]: latest }));
      await loadWorkspace();
      await refreshProjectAssets();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "镜头运行失败");
    } finally {
      setShotRunning(false);
    }
  }, [loadWorkspace, refreshProjectAssets, selectedShot, shotRunning]);

  const cancelSelectedGeneration = useCallback(async () => {
    if (!selectedNodeGeneration || !["queued", "running"].includes(selectedNodeGeneration.status)) return;
    setError(null);
    setSyncState("saving");
    try {
      const cancelled = await api.cancelGeneration(selectedNodeGeneration.id);
      setGenerations((current) => ({ ...current, [cancelled.shot_id]: cancelled }));
      setGenerationHistory((current) => ({
        ...current,
        [cancelled.shot_id]: [
          cancelled,
          ...(current[cancelled.shot_id] ?? []).filter((item) => item.id !== cancelled.id),
        ],
      }));
      setPendingNodeId(null);
      setSyncState("saved");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消生成任务失败");
      setSyncState("error");
    }
  }, [selectedNodeGeneration]);

  const handleNodeClick = useCallback((_: MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const connectNodes = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) return;
    if (connection.source === connection.target) {
      setError("节点不能连接到自身");
      return;
    }
    setEdges((current) => {
      if (current.some((edge) => edge.source === connection.source && edge.target === connection.target)) {
        setError("这两个节点已经连线");
        return current;
      }
      if (connectionCreatesCycle(current, connection.source, connection.target)) {
        setError("连线会形成循环，请从上游节点连接到下游节点");
        return current;
      }
      setError(null);
      return addEdge({ ...connection, id: crypto.randomUUID(), type: "studio" }, current);
    });
  }, [setEdges]);

  const addCanvasNode = useCallback(() => {
    if (!selectedShot) return;
    const id = crypto.randomUUID();
    const config = {
      node_id: id,
      mode: null,
      prompt: "",
      aspect_ratio: "16:9",
      resolution: "2K",
      quality: "标准",
      count: 1,
      duration_seconds: 5,
      panorama: false,
      seed: -1,
    };
    const presentation = presentNode("generator", config, selectedShot);
    const nodeWidth = 290;
    const nodeHeight = 158;
    const centerPosition = canvasCenter
      ? { x: canvasCenter.x - nodeWidth / 2, y: canvasCenter.y - nodeHeight / 2 }
      : null;
    setNodes((current) => [
      ...current,
      {
        id,
        type: "studio",
        position: centerPosition ?? { x: 430 + (current.length % 4) * 42, y: 430 + (current.length % 3) * 36 },
        data: { kind: "generator", version: "1.0", config, ...presentation },
      },
    ]);
    setSelectedNodeId(id);
  }, [canvasCenter, selectedShot, setNodes]);

  const updateSelectedNodeConfig = useCallback((patch: Record<string, unknown>) => {
    if (!selectedNodeId || !selectedShot) return;
    setNodes((current) => current.map((node) => {
      if (node.id !== selectedNodeId) return node;
      const config = { ...node.data.config, ...patch };
      return {
        ...node,
        data: {
          ...node.data,
          config,
          ...presentNode(node.data.kind, config, selectedShot, selectedNodeGeneration),
        },
      };
    }));
  }, [selectedNodeGeneration, selectedNodeId, selectedShot, setNodes]);

  const uploadSelectedNodeAssets = useCallback(async (files: File[]) => {
    if (!selectedNodeId || !selectedShot || files.length === 0 || uploadingNodeId) return;
    const targetNodeId = selectedNodeId;
    const existingCount = selectedNode?.id === targetNodeId
      ? uploadedAssets(selectedNode.data.config).length
      : 0;
    const availableSlots = Math.max(0, 8 - existingCount);
    if (availableSlots === 0) {
      setError("每个节点最多上传 8 张参考图片，请先移除不需要的图片");
      return;
    }
    const selectedFiles = files.slice(0, availableSlots);
    const invalid = selectedFiles.find((file) => (
      !["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)
      || file.size > 10 * 1024 * 1024
    ));
    if (invalid) {
      setError(`${invalid.name} 格式不支持或超过 10MB`);
      return;
    }

    setUploadingNodeId(targetNodeId);
    setError(null);
    try {
      const uploaded = await Promise.all(selectedFiles.map((file) => api.uploadAsset(file, projectId)));
      void api.listAssets(projectId).then(setProjectAssets).catch(() => undefined);
      setNodes((current) => current.map((node) => {
        if (node.id !== targetNodeId) return node;
        const currentAssets = uploadedAssets(node.data.config);
        const currentMode = creationMode(node.data.config);
        const currentProviderId = textConfig(node.data.config, "provider", "");
        const currentProvider = providerCapabilities.find((provider) => (
          provider.kind === "image" && provider.id === currentProviderId
        ));
        const preferredImageProvider = providerCapabilities.find((provider) => (
          provider.kind === "image"
          && provider.configured
          && (provider.id === "qwen" || provider.id === "google_genai")
        ));
        const needsImageProvider = !currentMode
          || (currentMode === "image" && (
            !currentProvider?.configured
            || (currentProvider.id !== "qwen" && currentProvider.id !== "google_genai")
          ));
        const config = {
          ...node.data.config,
          ...(needsImageProvider && preferredImageProvider ? {
            mode: "image",
            provider: preferredImageProvider?.id,
            model: preferredImageProvider?.model,
          } : !currentMode ? { mode: "image" } : {}),
          uploaded_assets: [...currentAssets, ...uploaded].slice(0, 8),
        };
        return {
          ...node,
          data: {
            ...node.data,
            config,
            ...presentNode(node.data.kind, config, selectedShot, selectedNodeGeneration),
          },
        };
      }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "图片上传失败");
      setSyncState("error");
    } finally {
      setUploadingNodeId((current) => current === targetNodeId ? null : current);
    }
  }, [projectId, providerCapabilities, selectedNode, selectedNodeGeneration, selectedNodeId, selectedShot, setNodes, uploadingNodeId]);

  const uploadProjectAssets = useCallback(async (files: File[]) => {
    if (!files.length || assetLibraryUploading) return;
    const invalid = files.find((file) => (
      !["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)
      || file.size > 10 * 1024 * 1024
    ));
    if (invalid) {
      setAssetLibraryError(`${invalid.name} 格式不支持或超过 10MB`);
      return;
    }
    setAssetLibraryUploading(true);
    setAssetLibraryError(null);
    try {
      await Promise.all(files.map((file) => api.uploadAsset(file, projectId)));
      await refreshProjectAssets();
    } catch (cause) {
      setAssetLibraryError(cause instanceof Error ? cause.message : "资产上传失败");
    } finally {
      setAssetLibraryUploading(false);
    }
  }, [assetLibraryUploading, projectId, refreshProjectAssets]);

  const selectProjectAsset = useCallback((asset: ProjectAsset) => {
    if (!selectedNodeId || !selectedShot || asset.kind !== "image") return;
    setNodes((current) => current.map((node) => {
      if (node.id !== selectedNodeId) return node;
      const currentAssets = uploadedAssets(node.data.config);
      if (currentAssets.some((item) => item.asset_id === asset.id)) return node;
      const currentMode = creationMode(node.data.config);
      const currentProviderId = textConfig(node.data.config, "provider", "");
      const currentProvider = providerCapabilities.find((provider) => (
        provider.kind === "image" && provider.id === currentProviderId
      ));
      const preferredImageProvider = providerCapabilities.find((provider) => (
        provider.kind === "image"
        && provider.configured
        && (provider.id === "qwen" || provider.id === "google_genai")
      ));
      const needsImageProvider = !currentMode
        || (currentMode === "image" && (
          !currentProvider?.configured
          || (currentProvider.id !== "qwen" && currentProvider.id !== "google_genai")
        ));
      const config = {
        ...node.data.config,
        ...(needsImageProvider && preferredImageProvider ? {
          mode: "image",
          provider: preferredImageProvider.id,
          model: preferredImageProvider.model,
        } : !currentMode ? { mode: "image" } : {}),
        uploaded_assets: [
          ...currentAssets,
          {
            id: asset.source_upload_id ?? asset.id,
            asset_id: asset.id,
            filename: asset.filename,
            kind: "image",
            content_type: asset.content_type,
            size: asset.size,
            url: asset.url,
          },
        ].slice(0, 8),
      };
      return {
        ...node,
        data: {
          ...node.data,
          config,
          ...presentNode(node.data.kind, config, selectedShot, selectedNodeGeneration),
        },
      };
    }));
    setAssetLibraryError(null);
  }, [providerCapabilities, selectedNodeGeneration, selectedNodeId, selectedShot, setNodes]);

  const deleteProjectAsset = useCallback(async (asset: ProjectAsset) => {
    if (deletingAssetId) return;
    setDeletingAssetId(asset.id);
    setAssetLibraryError(null);
    try {
      await api.deleteAsset(asset.id);
      setProjectAssets((current) => current.filter((item) => item.id !== asset.id));
    } catch (cause) {
      setAssetLibraryError(cause instanceof Error ? cause.message : "资产删除失败");
    } finally {
      setDeletingAssetId(null);
    }
  }, [deletingAssetId]);

  const deleteSelectedNode = useCallback(() => {
    if (!selectedNodeId) return;
    setNodes((current) => current.filter((node) => node.id !== selectedNodeId));
    setEdges((current) => current.filter((edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId));
    setSelectedNodeId(null);
  }, [selectedNodeId, setEdges, setNodes]);

  return (
    <main className="studio-shell">
      <StudioHeader
        currentUser={currentUser}
        project={project}
        selectedShot={selectedShot}
        syncState={syncState}
        error={error}
        agentOpen={agentOpen}
        onSettingsOpenChange={setSettingsOpen}
        onSelectShot={(shotId) => {
          setSelectedShotId(shotId);
          setSelectedNodeId(null);
        }}
        onAgentOpenChange={setAgentOpen}
        onReload={() => void loadWorkspace()}
        onBackToDashboard={() => router.push("/dashboard")}
        onLogout={onLogout}
        onRunShot={() => void runCurrentShot()}
        shotRunning={shotRunning}
      />

      <LlmSettings
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        onSaved={() => {
          void api.listProviders().then(setProviderCapabilities);
        }}
      />

      {!project ? (
        <section className="workspace-gate">
          <Card className="workspace-gate__card">
            <CardHeader>
              <Badge variant="outline" className="gate-index"><Database />PROJECT / DATABASE</Badge>
              <CardTitle>
                <h1>{syncState === "loading" ? "正在读取工作区" : syncState === "error" ? "API 尚未连接" : "数据库里还没有项目"}</h1>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {syncState === "loading" ? (
                <div className="gate-skeletons" aria-label="正在加载">
                  <Skeleton /><Skeleton />
                </div>
              ) : syncState === "error" ? (
                <Alert variant="destructive">
                  <CircleAlert />
                  <AlertTitle>无法读取项目数据</AlertTitle>
                  <AlertDescription>{error ?? "请先运行 pnpm api:dev，然后重新同步。"}</AlertDescription>
                </Alert>
              ) : (
                <p>创建示例项目后，项目和镜头会真正写入 SQLite，刷新页面仍然存在。</p>
              )}
              <div className="gate-actions">
                {syncState === "error" ? (
                  <Button type="button" onClick={() => void loadWorkspace()}><RefreshCw />重新连接 API</Button>
                ) : syncState !== "loading" ? (
                  <Button type="button" onClick={() => void createDemoProject()}><Plus />创建真实示例项目</Button>
                ) : null}
                <Badge variant="secondary" className="gate-endpoint">GET /api/projects</Badge>
              </div>
            </CardContent>
          </Card>
        </section>
      ) : (
        <section className={`studio-body ${selectedShot ? "" : "studio-body--agent-only"}`}>
          {selectedShot ? (
            <CanvasSideRail
              onAddNode={addCanvasNode}
              onToggleShots={() => {
                setAssetLibraryOpen(false);
                setShotRailOpen((open) => !open);
              }}
              onToggleAssets={() => {
                setShotRailOpen(false);
                void refreshProjectAssets();
                setAssetLibraryOpen((open) => !open);
              }}
              onToggleAgent={() => setAgentOpen((open) => !open)}
            />
          ) : null}

          {selectedShot ? (
            <>
              <ShotRail
                project={project}
                selectedShotId={selectedShot.id}
                open={shotRailOpen}
                totalDuration={totalDuration}
                onClose={() => setShotRailOpen(false)}
                onAddShot={() => void addShot()}
                onSelectShot={(shotId) => {
                  setSelectedShotId(shotId);
                  setSelectedNodeId(null);
                }}
              />

              <AssetLibrary
                open={assetLibraryOpen}
                assets={projectAssets}
                selectedNodeId={selectedNode?.data.kind === "generator" ? selectedNodeId : null}
                uploading={assetLibraryUploading}
                deletingAssetId={deletingAssetId}
                error={assetLibraryError}
                onClose={() => setAssetLibraryOpen(false)}
                onUpload={(files) => void uploadProjectAssets(files)}
                onInsert={selectProjectAsset}
                onDelete={(asset) => void deleteProjectAsset(asset)}
                onRefresh={() => void refreshProjectAssets()}
              />
            </>
          ) : null}

          {selectedShot && workflowReady && selectedNode ? (
            <>
              <section className="canvas-stage" aria-label="工作流画布">
                <div className="canvas-toolbar">
                  <div><span className="kicker">SHOT {String(selectedShot.sequence_number).padStart(2, "0")} / DATABASE WORKFLOW</span><h1>{selectedShot.title}</h1></div>
                  <div className="canvas-toolbar__tools">
                    <div className="canvas-history-tools" aria-label="画布历史操作">
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => restoreCanvasHistory(-1)} disabled={!historyState.canUndo} aria-label="撤销画布操作" title="撤销">
                        <Undo2 />
                      </Button>
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => restoreCanvasHistory(1)} disabled={!historyState.canRedo} aria-label="重做画布操作" title="重做">
                        <Redo2 />
                      </Button>
                    </div>
                    <Badge variant="outline" className="runtime-status"><span className="pulse pulse--synced" />节点与连线自动保存</Badge>
                  </div>
                </div>
                <div ref={flowWrapRef} className="flow-wrap">
                  <div className="canvas-toolbelt" aria-label="添加工作流节点">
                    <span>ADD NODE</span>
                    <Button type="button" variant="secondary" size="sm" onClick={addCanvasNode}>
                      <Plus />空白节点
                    </Button>
                  </div>
                  <StudioNodeActionsContext.Provider value={studioNodeActions}>
                    <ReactFlow
                      key={activeShotId}
                      nodes={nodes}
                      edges={edges}
                      nodeTypes={workspaceNodeTypes}
                      edgeTypes={edgeTypes}
                      onNodesChange={onNodesChange}
                      onEdgesChange={onEdgesChange}
                      onConnect={connectNodes}
                      onNodeClick={handleNodeClick}
                      onPaneClick={() => setSelectedNodeId(null)}
                      onMove={(_, viewport) => setCanvasViewport(viewport)}
                      onNodesDelete={(deleted) => {
                        const deletedIds = new Set(deleted.map((node) => node.id));
                        setEdges((current) => current.filter((edge) => !deletedIds.has(edge.source) && !deletedIds.has(edge.target)));
                        if (deleted.some((node) => node.id === selectedNodeId)) setSelectedNodeId(null);
                      }}
                      defaultViewport={canvasViewport}
                      minZoom={0.55}
                      maxZoom={1.45}
                      proOptions={{ hideAttribution: true }}
                    >
                      <Background variant={BackgroundVariant.Dots} gap={22} size={0.8} color="#39393c" />
                      <Controls />
                      <MiniMap pannable zoomable nodeColor={(node) => (node.data as StudioNodeData).stage === "done" ? "#65bdc2" : "#617c8f"} />
                    </ReactFlow>
                  </StudioNodeActionsContext.Provider>
                  {selectedNodeId && selectedNode.data.kind === "generator" ? (
                    <NodeComposer
                      node={selectedNode}
                      generation={selectedNodeGeneration}
                      generationHistory={shotGenerationHistory.filter((item) => item.node_id === selectedNodeId)}
                      providers={providerCapabilities}
                      assets={projectAssets}
                      contexts={selectedContexts}
                      busy={selectedNodeBusy}
                      uploading={uploadingNodeId === selectedNodeId}
                      style={composerStyle}
                      onUpdate={updateSelectedNodeConfig}
                      onUpload={(files) => void uploadSelectedNodeAssets(files)}
                      onSelectAsset={selectProjectAsset}
                      onRun={() => void executeGeneration()}
                      onRetry={() => void retrySelectedGeneration()}
                      onCancel={() => void cancelSelectedGeneration()}
                      onSelectGeneration={(generationId) => {
                        const selected = shotGenerationHistory.find((item) => item.id === generationId);
                        if (selected && selectedShot) {
                          setGenerations((current) => ({ ...current, [selectedShot.id]: selected }));
                        }
                      }}
                      onDelete={deleteSelectedNode}
                    />
                  ) : null}
                </div>
                <TimelineStrip
                  selectedShot={selectedShot}
                  shots={project.shots}
                  totalDuration={totalDuration}
                />
              </section>

            </>
          ) : selectedShot ? (
            <section className="workspace-gate workspace-gate--embedded">
              <Badge variant="outline" className="gate-index"><Database />WORKFLOW / DATABASE</Badge>
              <h1>正在读取画布</h1><p>加载节点、连线和上次保存的视口位置。</p>
              <div className="gate-skeletons gate-skeletons--embedded"><Skeleton /><Skeleton /></div>
            </section>
          ) : null}

          <ChatAgent
            open={agentOpen}
            project={project}
            shot={selectedShot}
            node={selectedNodeId ? selectedNode : undefined}
            nodes={nodes}
            assets={projectAssets}
            generation={selectedNodeId ? selectedNodeGeneration : selectedGeneration}
            canvasVersion={workflow?.updated_at}
            canvasRevision={workflow?.revision}
            canvasCenter={canvasCenter}
            canvasSyncing={syncState !== "saved"}
            onEnsureShot={ensureShotForAgent}
            canClose={Boolean(selectedShot)}
            onCanvasChanged={reloadActiveCanvas}
            onClose={() => setAgentOpen(false)}
          />
        </section>
      )}
    </main>
  );
}
