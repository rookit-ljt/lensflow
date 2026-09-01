import {
  AudioLines,
  ImageIcon,
  Type,
  Video,
  type LucideIcon,
} from "lucide-react";

import type { UploadedAsset } from "@/lib/api";

import type {
  CreationMode,
  H3ReferenceBinding,
  H3ReferenceRole,
  Stage,
  SyncState,
  VideoReferenceMode,
} from "./studio-types";

type CreationModeDefinition = {
  label: string;
  eyebrow: string;
  placeholder: string;
  models: string[];
  icon: LucideIcon;
};

export const stageLabel: Record<Stage, string> = {
  done: "已持久化",
  running: "执行中",
  ready: "配置完成",
  waiting: "等待接入",
};

export const syncLabel: Record<SyncState, string> = {
  loading: "正在读取 API",
  saved: "数据已持久化",
  saving: "正在写入数据库",
  error: "API 连接失败",
};

export const demoShots = [
  {
    title: "海岸公路",
    description: "车辆沿着凌晨的海岸公路驶入雾区。",
    visual_prompt: "远景，冷雾覆盖海岸线，旧车从画面右侧缓慢驶入，镜头平稳横移。",
    duration_seconds: 4,
  },
  {
    title: "末班列车",
    description: "空荡车厢掠过稀疏的沿海灯火。",
    visual_prompt: "车厢内固定机位，玻璃反射人物侧脸，窗外灯火高速掠过。",
    duration_seconds: 6,
  },
  {
    title: "雨夜抵达",
    description: "角色从无人的站台走向出口，镜头缓慢后退。",
    visual_prompt: "低机位跟拍，深蓝雨衣，潮湿空气，远处钠灯形成长条倒影。",
    duration_seconds: 5,
  },
];

export const creationModeOrder: CreationMode[] = ["text", "image", "video", "audio"];

// Audio remains in the schema for backwards compatibility with saved drafts,
// but is intentionally hidden until a real audio Provider is available.
export const visibleCreationModeOrder: CreationMode[] = ["text", "image", "video"];

export const creationModes: Record<CreationMode, CreationModeDefinition> = {
  text: {
    label: "文本生成",
    eyebrow: "TEXT CREATION",
    placeholder: "描述要生成或改写的文本，例如分镜、对白、旁白……",
    models: ["默认文本模型", "分镜生成", "叙事扩写", "对白润色"],
    icon: Type,
  },
  image: {
    label: "图片生成",
    eyebrow: "IMAGE CREATION",
    placeholder: "描述画面、构图、人物和光线，也可以使用 @ 引用资产……",
    models: ["服务端默认图片模型"],
    icon: ImageIcon,
  },
  video: {
    label: "视频生成",
    eyebrow: "VIDEO CREATION",
    placeholder: "描述镜头动作、主体运动、运镜和节奏……",
    models: ["minimax-h3-local"],
    icon: AudioLines,
  },
  audio: {
    label: "音频生成（即将接入）",
    eyebrow: "AUDIO CREATION",
    placeholder: "输入旁白、对白，或描述需要的环境音和音效……",
    models: ["中文旁白 · Mock", "角色对白 · Mock", "环境音效 · Mock"],
    icon: Video,
  },
};

export const aspectRatios = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];
export const resolutions = ["720P", "1080P", "2K", "4K"];
export const localVideoSizes = [
  { value: "256", label: "256 × 256 · 快速测试" },
  { value: "512", label: "512 × 512 · 预览" },
  { value: "preview", label: "模型预览规格 · preview" },
  { value: "720", label: "1280 × 720 · 成片" },
];
export const qualityLevels = ["草稿", "标准", "精细"];

export function creationMode(config: Record<string, unknown>): CreationMode | null {
  const value = config.mode;
  return creationModeOrder.includes(value as CreationMode) ? value as CreationMode : null;
}

export function textConfig(
  config: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  return typeof config[key] === "string" ? config[key] : fallback;
}

export function numberConfig(
  config: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  return typeof config[key] === "number" ? config[key] : fallback;
}

export function booleanConfig(
  config: Record<string, unknown>,
  key: string,
  fallback: boolean,
): boolean {
  return typeof config[key] === "boolean" ? config[key] : fallback;
}

export function uploadedAssets(config: Record<string, unknown>): UploadedAsset[] {
  const value = config.uploaded_assets;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is UploadedAsset => (
    typeof item === "object"
    && item !== null
    && typeof item.id === "string"
    && typeof item.filename === "string"
    && item.kind === "image"
    && typeof item.content_type === "string"
    && typeof item.size === "number"
    && typeof item.url === "string"
  ));
}

export function frameNodeSelection(
  config: Record<string, unknown>,
  key: "first_frame_node_id" | "last_frame_node_id",
  fallback: string,
  availableNodeIds: string[],
): string {
  const value = config[key];
  if (typeof value !== "string") return fallback;
  if (!value) return "";
  return availableNodeIds.includes(value) ? value : fallback;
}

const referenceRoles: H3ReferenceRole[] = ["character", "scene", "style", "prop", "effect"];

export function videoReferenceMode(config: Record<string, unknown>): VideoReferenceMode {
  const value = config.video_reference_mode;
  if (value === "text" || value === "keyframe" || value === "ref2va") return value;
  const hasFrameSelection = Boolean(
    textConfig(config, "first_frame_node_id", "")
    || textConfig(config, "last_frame_node_id", ""),
  );
  return hasFrameSelection ? "keyframe" : "text";
}

export function h3ReferenceBindings(config: Record<string, unknown>): H3ReferenceBinding[] {
  const value = config.reference_bindings;
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map((item, index) => ({
      nodeId: typeof item.node_id === "string"
        ? item.node_id
        : typeof item.nodeId === "string" ? item.nodeId : "",
      order: typeof item.order === "number" ? item.order : index + 1,
      role: referenceRoles.includes(item.role as H3ReferenceRole)
        ? item.role as H3ReferenceRole
        : "scene",
      name: typeof item.name === "string" ? item.name : "",
      preserve: typeof item.preserve === "string" ? item.preserve : "",
      mutable: typeof item.mutable === "string" ? item.mutable : "pose, camera angle, scale, and lighting",
      exclude: typeof item.exclude === "string" ? item.exclude : "watermark, logo, arrow, annotation, and reference-sheet background",
    }))
    .filter((item) => item.nodeId)
    .sort((left, right) => left.order - right.order)
    .map((item, index) => ({ ...item, order: index + 1 }));
}

export function serializeH3ReferenceBindings(bindings: H3ReferenceBinding[]): Record<string, unknown>[] {
  return bindings.map((binding, index) => ({
    node_id: binding.nodeId,
    order: index + 1,
    role: binding.role,
    name: binding.name,
    preserve: binding.preserve,
    mutable: binding.mutable,
    exclude: binding.exclude,
  }));
}

const roleDefaults: Record<H3ReferenceRole, { name: string; preserve: string }> = {
  character: {
    name: "the referenced character",
    preserve: "facial identity, body proportions, hair or fur, costume, accessories, and signature equipment",
  },
  scene: {
    name: "the referenced environment",
    preserve: "architecture, spatial layout, atmosphere, color palette, lighting, material realism, and destruction or prop density",
  },
  style: {
    name: "the referenced visual style",
    preserve: "color treatment, contrast, texture, lens character, lighting language, and overall visual mood",
  },
  prop: {
    name: "the referenced prop",
    preserve: "shape, proportions, materials, surface details, color, and recognizable design features",
  },
  effect: {
    name: "the referenced visual effect",
    preserve: "energy shape, particles, color, glow behavior, density, and interaction with the environment",
  },
};

export function defaultH3ReferenceBinding(
  nodeId: string,
  order: number,
  title: string,
  role: H3ReferenceRole = order === 1 ? "scene" : "character",
): H3ReferenceBinding {
  const defaults = roleDefaults[role];
  return {
    nodeId,
    order,
    role,
    name: title.trim() || defaults.name,
    preserve: defaults.preserve,
    mutable: "pose, camera angle, scale, motion, and scene-dependent lighting",
    exclude: "watermark, logo, arrow, annotation, duplicate subjects, and reference-sheet background",
  };
}

export function compileH3Ref2vaPrompt(
  intent: string,
  bindings: H3ReferenceBinding[],
  cameraMotion = "自动",
): string {
  const ordered = bindings.slice(0, 12).map((binding, index) => ({ ...binding, order: index + 1 }));
  if (!intent.trim() || ordered.length === 0) return "";

  const intentText = intent.trim();
  const soundscapeMarker = "overall_soundscape:";
  const musicMarker = "non_diegetic_music:";
  const detailedMarker = "detailed_description:";
  const integratedMarker = "integrated_multimodal_description:";
  const soundscapeIndex = intentText.indexOf(soundscapeMarker);
  const musicIndex = intentText.indexOf(musicMarker);
  let visualIntent = intentText;
  const detailedIndex = visualIntent.indexOf(detailedMarker);
  const integratedIndex = visualIntent.indexOf(integratedMarker);
  if (detailedIndex >= 0) visualIntent = visualIntent.slice(detailedIndex + detailedMarker.length);
  else if (integratedIndex >= 0) visualIntent = visualIntent.slice(integratedIndex + integratedMarker.length);
  const embeddedSoundscapeIndex = visualIntent.indexOf(soundscapeMarker);
  if (embeddedSoundscapeIndex >= 0) visualIntent = visualIntent.slice(0, embeddedSoundscapeIndex);
  visualIntent = visualIntent.trim();
  const embeddedSoundscape = soundscapeIndex >= 0
    ? intentText.slice(
        soundscapeIndex + soundscapeMarker.length,
        musicIndex > soundscapeIndex ? musicIndex : undefined,
      ).trim()
    : "";
  const embeddedMusic = musicIndex >= 0
    ? intentText.slice(musicIndex + musicMarker.length).trim()
    : "";

  const subjects = ordered.map((binding, index) => {
    const picture = index + 1;
    const defaults = roleDefaults[binding.role];
    const name = binding.name.trim() || defaults.name;
    const preserve = binding.preserve.trim() || defaults.preserve;
    return `<Subject ${picture}> is ${name} from <Picture ${picture}>, used as the ${binding.role} reference. Preserve ${preserve}.`;
  }).join("\n");
  const subjectList = ordered.map((_, index) => `<Subject ${index + 1}>`).join(", ");
  const retention = ordered.map((binding, index) => {
    const subject = index + 1;
    const defaults = roleDefaults[binding.role];
    const preserve = binding.preserve.trim() || defaults.preserve;
    const mutable = binding.mutable.trim() || "pose, camera angle, scale, motion, and scene-dependent lighting";
    return `<Subject ${subject}> (appears in [Shot 1]): fully_preserved - Retain ${preserve}; only adapt ${mutable}.`;
  }).join("\n");
  const avoid = Array.from(new Set(ordered.flatMap((binding) => (
    binding.exclude.split(",").map((item) => item.trim()).filter(Boolean)
  )))).join(", ");
  const camera = cameraMotion && cameraMotion !== "自动"
    ? ` Use a ${cameraMotion} camera movement.`
    : "";
  const shotDescription = /^\[Shot\s+\d+\]/i.test(visualIntent)
    ? visualIntent
    : `[Shot 1] ${visualIntent}`;

  return [
    "subject_definitions:",
    subjects,
    "",
    "summary:",
    `[reference generation] The target video uses ${subjectList} to realize the requested shot while preserving each reference's assigned identity and design function.`,
    "",
    "retention_analysis:",
    retention,
    "",
    "detailed_description:",
    "The target video uses coherent cinematic audiovisual generation with natural spatial depth, consistent materials, and temporally stable subject identity.",
    `${shotDescription}${camera} Keep all referenced subjects visually consistent throughout the shot. Do not reproduce ${avoid || "watermarks, logos, arrows, annotations, or reference-sheet layouts"}.`,
    "",
    "overall_soundscape:",
    embeddedSoundscape || "Use natural diegetic ambience and action-synchronized environmental sound appropriate to the described scene.",
    "",
    "non_diegetic_music:",
    embeddedMusic || "N/A",
  ].join("\n");
}

export function imageAspectRatio(config: Record<string, unknown>): number {
  const value = textConfig(config, "aspect_ratio", "16:9");
  const [width, height] = value.split(":").map(Number);
  return width > 0 && height > 0 ? width / height : 16 / 9;
}

export function renderableImageUrl(
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined;
  return /^(https?:\/\/|data:image\/|blob:)/i.test(value) ? value : undefined;
}

export function renderableVideoUrl(
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined;
  return /^(https?:\/\/|blob:)/i.test(value) ? value : undefined;
}

export function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}
