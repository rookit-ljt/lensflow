const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export interface CurrentUser {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export function generationDownloadUrl(generationId: string): string {
  return `${API_URL}/api/generations/${generationId}/download`;
}

export function projectExportUrl(projectId: string): string {
  return `${API_URL}/api/projects/${projectId}/export`;
}

export type ShotStatus = "draft" | "ready" | "generating" | "review" | "approved";

export interface Shot {
  id: string;
  project_id: string;
  sequence_number: number;
  title: string;
  description: string;
  visual_prompt: string;
  duration_seconds: number;
  status: ShotStatus;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  status: "draft" | "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface Project extends ProjectSummary {
  shots: Shot[];
}

export interface ShotInput {
  sequence_number: number;
  title: string;
  description?: string;
  visual_prompt?: string;
  duration_seconds?: number;
}

export type GenerationStatus = "queued" | "running" | "succeeded" | "failed";

export interface Generation {
  id: string;
  shot_id: string;
  provider: string;
  kind: "text" | "image" | "video";
  model: string | null;
  node_id: string | null;
  input_text: string | null;
  temperature: number;
  max_tokens: number;
  parameters: Record<string, unknown>;
  status: GenerationStatus;
  progress: number;
  celery_task_id: string | null;
  provider_job_id: string | null;
  output_url: string | null;
  output_text: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadedAsset {
  id: string;
  asset_id?: string | null;
  filename: string;
  kind: "image";
  content_type: string;
  size: number;
  url: string;
}

export interface ProjectAsset {
  id: string;
  user_id: string;
  project_id: string | null;
  shot_id: string | null;
  source_upload_id: string | null;
  source_generation_id: string | null;
  kind: string;
  role: string;
  filename: string;
  content_type: string;
  size: number;
  url: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WorkflowNodeRecord {
  id: string;
  type: string;
  version: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
}

export interface WorkflowEdgeRecord {
  id: string;
  source: string;
  target: string;
  source_handle: string | null;
  target_handle: string | null;
}

export interface Workflow {
  id: string;
  shot_id: string;
  schema_version: string;
  nodes: WorkflowNodeRecord[];
  edges: WorkflowEdgeRecord[];
  viewport: { x: number; y: number; zoom: number };
  revision: number;
  last_operation_id: string | null;
  created_at: string;
  updated_at: string;
}

export type WorkflowWrite = Pick<Workflow, "schema_version" | "nodes" | "edges" | "viewport">
  & { base_revision?: number | null; operation_id?: string };

export interface ProviderCapability {
  id: "mock" | "ark_seedream" | "google_genai" | "openai_compatible" | "qwen" | "local_h3";
  kind: "text" | "image" | "video";
  label: string;
  configured: boolean;
  model: string;
  models: string[];
  requires_api_key: boolean;
}

export interface RuntimeSettings {
  runtime_enabled: boolean;
  environment: string;
  text_provider: string;
  text_model: string;
  text_base_url: string;
  text_configured: boolean;
  image_provider: string;
  image_model: string;
  image_base_url: string;
  image_configured: boolean;
  agent_provider: string;
  agent_model: string;
  qwen_text_model: string;
  qwen_text_base_url: string;
  qwen_configured: boolean;
  qwen_image_model: string;
  qwen_image_base_url: string;
  qwen_image_configured: boolean;
  local_video_model: string;
  local_video_base_url: string;
  local_video_request_timeout_seconds: number;
  local_video_configured: boolean;
}

export interface RuntimeSettingsPayload {
  provider: "qwen" | "openai_compatible" | "local_h3";
  kind: "text" | "image" | "video";
  api_key?: string;
  model: string;
  base_url?: string;
  apply_to_agent?: boolean;
}

export interface RuntimeSettingsTestResult {
  ok: boolean;
  provider: string;
  model: string;
  message: string;
}

export type AgentRunStatus =
  | "thinking"
  | "planning"
  | "waiting_user"
  | "waiting_approval"
  | "executing"
  | "waiting_external_job"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentThread {
  id: string;
  project_id: string;
  title: string;
  summary: string;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface AgentMessage {
  id: string;
  thread_id: string;
  run_id: string | null;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  message_type: string;
  message_metadata: Record<string, unknown>;
  created_at: string;
}

export type AgentMention = {
  type: "asset" | "node" | "shot" | "generation";
  id: string;
  label: string;
};

export type AgentSkill = {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  tags: string[];
  source: string;
  source_url: string;
  stars: number | null;
  license: string;
  featured: boolean;
  instruction?: string;
};

export type CanvasPatchOperation =
  | {
      type: "update_node_config";
      id: string;
      description: string;
      node_id: string;
      config_patch: Record<string, unknown>;
    }
  | {
      type: "create_node";
      id: string;
      description: string;
      node_id: string;
      node_type: "generator";
      position: { x: number; y: number };
      config: Record<string, unknown>;
    }
  | {
      type: "connect_nodes";
      id: string;
      description: string;
      edge_id: string;
      source: string;
      target: string;
    }
  | {
      type: "bind_asset";
      id: string;
      description: string;
      node_id: string;
      asset_id: string;
      role: "reference" | "first_frame" | "last_frame";
    };

export interface AgentApproval {
  id: string;
  run_id: string;
  status: "pending" | "approved" | "rejected";
  summary: string;
  risk_level: string;
  patch: {
    version: "1.0";
    shot_id: string;
    base_canvas_version: string | null;
    operations: CanvasPatchOperation[];
  };
  decision_feedback: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface AgentInterruptOption {
  id: string;
  label: string;
  caption?: string;
  tone?: string;
  value?: unknown;
}

export interface AgentInterrupt {
  id: string;
  run_id: string;
  sequence: number;
  kind: string;
  decision_key: string;
  status: "pending" | "resolved" | "cancelled";
  title: string;
  description: string;
  payload: {
    presentation?: string;
    options?: AgentInterruptOption[];
    confirm_label?: string;
    [key: string]: unknown;
  };
  response: {
    option_id?: string;
    label?: string;
    value?: unknown;
    [key: string]: unknown;
  } | null;
  created_at: string;
  resolved_at: string | null;
}

export interface AgentRun {
  id: string;
  thread_id: string;
  status: AgentRunStatus;
  current_step: string;
  context_snapshot: Record<string, unknown>;
  canvas_version: string | null;
  provider: string | null;
  model: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  approval: AgentApproval | null;
}

export interface AgentApprovalDecisionResult {
  run: AgentRun;
  approval: AgentApproval;
  canvas_version: string | null;
  canvas_revision: number | null;
}

export interface AgentInterruptResumeResult {
  run: AgentRun;
  interrupt: AgentInterrupt;
  event_cursor: number;
}

export interface AgentEvent {
  id: string;
  run_id: string;
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new ApiError(body?.detail ?? `API request failed (${response.status})`, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  getCurrentUser: () => request<CurrentUser>("/api/auth/me"),
  register: (payload: { email: string; password: string; display_name: string }) =>
    request<CurrentUser>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  login: (payload: { email: string; password: string }) =>
    request<CurrentUser>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  loginWithGoogle: (credential: string) =>
    request<CurrentUser>("/api/auth/google", {
      method: "POST",
      body: JSON.stringify({ credential }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  uploadAsset: async (file: File, projectId?: string): Promise<UploadedAsset> => {
    const query = new URLSearchParams({ filename: file.name });
    if (projectId) query.set("project_id", projectId);
    const response = await fetch(`${API_URL}/api/uploads?${query}`, {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
      credentials: "include",
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null) as { detail?: string } | null;
      throw new Error(body?.detail ?? `上传失败（${response.status}）`);
    }
    return response.json() as Promise<UploadedAsset>;
  },
  listAssets: (projectId: string, params: { kind?: string; q?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.kind) query.set("kind", params.kind);
    if (params.q) query.set("q", params.q);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<ProjectAsset[]>(`/api/projects/${projectId}/assets${suffix}`);
  },
  getAsset: (assetId: string) => request<ProjectAsset>(`/api/assets/${assetId}`),
  deleteAsset: (assetId: string) => request<void>(`/api/assets/${assetId}`, {
    method: "DELETE",
  }),
  listProjects: () => request<ProjectSummary[]>("/api/projects"),
  getProject: (projectId: string) => request<Project>(`/api/projects/${projectId}`),
  createProject: (payload: { name: string; description?: string }) =>
    request<ProjectSummary>("/api/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createShot: (projectId: string, payload: ShotInput) =>
    request<Shot>(`/api/projects/${projectId}/shots`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateShot: (shotId: string, payload: Partial<Pick<Shot, "title" | "description" | "visual_prompt" | "duration_seconds" | "status">>) =>
    request<Shot>(`/api/shots/${shotId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  createGeneration: (shotId: string, payload: {
    provider: "mock" | "openai_compatible" | "ark_seedream" | "google_genai" | "qwen" | "local_h3";
    kind: "text" | "image" | "video";
    node_id?: string;
    prompt?: string;
    model?: string;
    temperature?: number;
    max_tokens?: number;
    parameters?: Record<string, unknown>;
  }) =>
    request<Generation>(`/api/shots/${shotId}/generations`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  runShot: (shotId: string) =>
    request<Generation[]>(`/api/shots/${shotId}/run`, { method: "POST" }),
  listGenerations: (shotId: string) =>
    request<Generation[]>(`/api/shots/${shotId}/generations`),
  getGeneration: (generationId: string) =>
    request<Generation>(`/api/generations/${generationId}`),
  retryGeneration: (generationId: string) =>
    request<Generation>(`/api/generations/${generationId}/retry`, { method: "POST" }),
  cancelGeneration: (generationId: string) =>
    request<Generation>(`/api/generations/${generationId}/cancel`, { method: "POST" }),
  submitFeedback: (payload: {
    category?: string;
    message: string;
    project_id?: string;
    shot_id?: string;
    generation_id?: string;
    context?: Record<string, unknown>;
  }) => request<{
    id: string;
    category: string;
    message: string;
    created_at: string;
  }>("/api/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  extractGenerationLastFrame: (generationId: string) =>
    request<UploadedAsset>(`/api/generations/${generationId}/last-frame`, {
      method: "POST",
    }),
  listProviders: () => request<ProviderCapability[]>("/api/providers"),
  getRuntimeSettings: () => request<RuntimeSettings>("/api/settings"),
  updateRuntimeSettings: (payload: RuntimeSettingsPayload) =>
    request<RuntimeSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  testRuntimeSettings: (payload: RuntimeSettingsPayload) =>
    request<RuntimeSettingsTestResult>("/api/settings/test", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getWorkflow: (shotId: string, options?: { empty?: boolean }) =>
    request<Workflow>(`/api/shots/${shotId}/workflow${options?.empty ? "?empty=true" : ""}`),
  saveWorkflow: (shotId: string, payload: WorkflowWrite) =>
    request<Workflow>(`/api/shots/${shotId}/workflow`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  listAgentThreads: (projectId: string) =>
    request<AgentThread[]>(`/api/projects/${projectId}/agent/threads`),
  createAgentThread: (projectId: string, payload: { title?: string } = {}) =>
    request<AgentThread>(`/api/projects/${projectId}/agent/threads`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listAgentMessages: (threadId: string) =>
    request<AgentMessage[]>(`/api/agent/threads/${threadId}/messages`),
  getPendingAgentApproval: (threadId: string) =>
    request<AgentApproval | null>(`/api/agent/threads/${threadId}/pending-approval`),
  getPendingAgentInterrupt: (threadId: string) =>
    request<AgentInterrupt | null>(`/api/agent/threads/${threadId}/pending-interrupt`),
  listAgentSkills: () => request<AgentSkill[]>("/api/agent/skills"),
  createAgentRun: (threadId: string, payload: {
    message: string;
    context: {
      project_id: string;
      shot_id?: string;
      selected_node_ids: string[];
      canvas_version?: string;
      canvas_revision?: number;
      canvas_center?: { x: number; y: number };
      mentions?: AgentMention[];
      skill_id?: string;
      skill_prompt?: string;
    };
  }) => request<AgentRun>(`/api/agent/threads/${threadId}/runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  getAgentRun: (runId: string) => request<AgentRun>(`/api/agent/runs/${runId}`),
  cancelAgentRun: (runId: string) => request<AgentRun>(`/api/agent/runs/${runId}/cancel`, {
    method: "POST",
  }),
  decideAgentApproval: (runId: string, payload: {
    decision: "approve" | "reject";
    feedback?: string;
  }) => request<AgentApprovalDecisionResult>(`/api/agent/runs/${runId}/approval`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  resumeAgentInterrupt: (runId: string, payload: {
    interrupt_id: string;
    response: Record<string, unknown>;
  }) => request<AgentInterruptResumeResult>(`/api/agent/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  listAgentEvents: (runId: string) =>
    request<AgentEvent[]>(`/api/agent/runs/${runId}/events`),
  agentEventStreamUrl: (runId: string, after = 0) =>
    `${API_URL}/api/agent/runs/${runId}/events/stream?after=${after}`,
};
