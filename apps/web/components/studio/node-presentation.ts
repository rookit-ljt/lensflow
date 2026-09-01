import { generationDownloadUrl, type Generation, type Shot, type WorkflowNodeRecord } from "@/lib/api";

import {
  creationMode,
  creationModes,
  imageAspectRatio,
  renderableImageUrl,
  renderableVideoUrl,
  textConfig,
} from "./studio-config";
import type { ContextReference, StudioFlowNode, StudioNodeData } from "./studio-types";

export function presentNode(
  kind: string,
  config: Record<string, unknown>,
  shot: Shot,
  generation?: Generation,
): Pick<StudioNodeData, "eyebrow" | "title" | "detail" | "stage" | "output" | "imageUrl" | "imageAspectRatio" | "videoUrl" | "downloadUrl"> {
  const hasPrompt = shot.visual_prompt.trim().length > 0;
  const isRunning = generation?.status === "queued" || generation?.status === "running";
  const hasSucceeded = generation?.status === "succeeded";
  const hasFailed = generation?.status === "failed";
  if (kind === "generator") {
    const mode = creationMode(config);
    const prompt = textConfig(config, "prompt", "").trim();
    const definition = mode ? creationModes[mode] : null;
    const belongsToNode = generation?.node_id === textConfig(config, "node_id", "");
    const hasStoredText = typeof config.text_content === "string";
    const textResult = mode === "text"
      ? hasStoredText ? String(config.text_content) : belongsToNode ? generation?.output_text : null
      : null;
    const generatedImageResult = generation?.kind === "image" && belongsToNode && hasSucceeded
      ? generation?.output_url
      : null;
    const sourceImageResult = textConfig(config, "source_image_url", "").trim() || null;
    const videoResult = generation?.kind === "video" && belongsToNode && hasSucceeded
      ? generation?.output_url
      : null;
    // A node created from an extracted video frame keeps source_image_url as its
    // generation input. Once that same node succeeds as a video generator, the
    // video is the node's result and must replace (not sit behind) the source image.
    const imageResult = videoResult ? null : generatedImageResult ?? sourceImageResult;
    return {
      eyebrow: definition?.label ?? "▣ 空白节点",
      title: textConfig(config, "title", definition?.label ?? "空白节点"),
      detail: textResult !== null
        ? textResult
        : imageResult
          ? generatedImageResult
            ? "图片已由服务端模型生成并写入执行回执。"
            : "已从上一个视频节点截取末帧，可继续作为图片参考使用。"
          : videoResult
            ? "本地 H3 已完成视频生成，可直接在节点中预览。"
          : (hasFailed && belongsToNode ? generation?.error ?? "生成失败" : prompt || "选择节点，在下方设置生成类型和内容。"),
      stage: isRunning && belongsToNode ? "running" : textResult !== null || imageResult || videoResult ? "done" : mode && prompt ? "ready" : "waiting",
      output: textResult !== null
        ? `${generation?.model || "默认模型"} · ${textResult.length} 字`
        : imageResult
          ? generatedImageResult
            ? `${generation?.model || "默认图片模型"} · ${generation?.provider}`
            : "视频末帧 · 图片素材"
          : videoResult
            ? `${generation?.model || "默认视频模型"} · ${generation?.provider}`
          : definition
            ? `${textConfig(config, "model", definition.models[0])} · ${textConfig(config, "aspect_ratio", "16:9")}`
            : "尚未定义",
      imageUrl: renderableImageUrl(imageResult),
      imageAspectRatio: imageResult
        ? typeof config.source_image_aspect_ratio === "number"
          ? config.source_image_aspect_ratio
          : imageAspectRatio(generation?.parameters ?? config)
        : undefined,
      videoUrl: renderableVideoUrl(videoResult),
      downloadUrl: generatedImageResult || videoResult
        ? generation ? generationDownloadUrl(generation.id) : undefined
        : sourceImageResult ?? undefined,
    };
  }
  if (kind === "shot") return {
    eyebrow: "☰ 文本",
    title: shot.title,
    detail: textConfig(
      config,
      "text_content",
      textConfig(config, "prompt", shot.description || "尚未填写镜头描述。"),
    ),
    stage: "done",
    output: `${shot.duration_seconds} 秒 · ${shot.status.toUpperCase()}`,
  };
  if (kind === "prompt") return {
    eyebrow: "☰ 提示词",
    title: "镜头提示",
    detail: textConfig(config, "detail", textConfig(config, "prompt", shot.visual_prompt || "在右侧检查器填写真实提示词。")),
    stage: textConfig(config, "detail", shot.visual_prompt).trim() ? "done" : "waiting",
    output: textConfig(config, "detail", shot.visual_prompt).trim()
      ? `${textConfig(config, "detail", shot.visual_prompt).length} 字 · 已保存`
      : undefined,
  };
  if (kind === "video") return {
    eyebrow: "PROVIDER GATEWAY",
    title: textConfig(config, "title", "生成镜头"),
    detail: isRunning
      ? "Celery 正在执行任务。"
      : hasSucceeded
        ? "Mock Provider 已完成编排验证，未生成真实视频。"
        : hasFailed
          ? generation.error ?? "任务执行失败。"
          : hasPrompt ? "输入已就绪，可运行无密钥 Mock Provider。" : "需要先填写镜头提示。",
    stage: isRunning ? "running" : hasSucceeded ? "done" : hasPrompt ? "ready" : "waiting",
    output: generation
      ? `${generation.progress}% · ${generation.provider.toUpperCase()} · ${generation.id.slice(0, 8)}`
      : "尚未创建任务",
  };
  if (kind === "review") return {
    eyebrow: "REVIEW",
    title: textConfig(config, "title", "选择版本"),
    detail: textConfig(config, "detail", "连接需要比较的结果节点。"),
    stage: "waiting",
  };
  return {
    eyebrow: textConfig(config, "eyebrow", kind.toUpperCase()),
    title: textConfig(config, "title", "未命名节点"),
    detail: textConfig(config, "detail", "在检查器中编辑节点说明。"),
    stage: kind === "note" ? "ready" : "waiting",
  };
}

export function recordToNode(
  record: WorkflowNodeRecord,
  shot: Shot,
  generation?: Generation,
): StudioFlowNode {
  const config = { ...record.config, node_id: record.id };
  return {
    id: record.id,
    type: "studio",
    deletable: !["shot", "prompt"].includes(record.type),
    position: record.position,
    data: {
      kind: record.type,
      version: record.version,
      config,
      ...presentNode(record.type, config, shot, generation),
    },
  };
}

export function nodeContextReference(
  node: StudioFlowNode,
  shot: Shot,
  history: Generation[],
): ContextReference | null {
  const sourceGeneration = history.find(
    (item) => item.node_id === node.id && item.status === "succeeded",
  );
  const latestImage = history.find(
    (item) => item.kind === "image" && item.status === "succeeded" && item.output_url,
  );
  const imageUrl = renderableImageUrl(
    sourceGeneration?.output_url
      ?? (node.data.kind === "review" ? latestImage?.output_url : undefined)
      ?? node.data.imageUrl,
  );
  if (imageUrl) {
    return { nodeId: node.id, title: "图片", kind: "image", source: "canvas", imageUrl };
  }

  const config = node.data.config;
  const text = (
    sourceGeneration?.output_text
    || (node.data.kind === "shot" ? textConfig(config, "text_content", shot.description) : "")
    || (node.data.kind === "prompt" ? textConfig(config, "detail", shot.visual_prompt) : "")
    || textConfig(config, "text_content", "")
    || textConfig(config, "prompt", "")
  ).trim();
  if (!text) return null;
  return {
    nodeId: node.id,
    title: node.data.kind === "prompt" ? "提示词" : "文本",
    kind: "text",
    source: "canvas",
    text,
  };
}
