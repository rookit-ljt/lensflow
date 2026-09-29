import { useRef, type CSSProperties } from "react";
import {
  ArrowUp,
  Braces,
  ChevronDown,
  ChevronUp,
  LoaderCircle,
  MousePointer2,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Type,
  Upload,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { MentionPicker, type MentionOption, type MentionRef } from "@/components/studio/mention-picker";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { Generation, ProjectAsset, ProviderCapability } from "@/lib/api";

import {
  aspectRatios,
  booleanConfig,
  creationMode,
  creationModes,
  compileH3Ref2vaPrompt,
  defaultH3ReferenceBinding,
  frameNodeSelection,
  h3ReferenceBindings,
  localVideoSizes,
  numberConfig,
  qualityLevels,
  resolutions,
  serializeH3ReferenceBindings,
  textConfig,
  uploadedAssets,
  visibleCreationModeOrder,
  videoReferenceMode,
} from "./studio-config";
import type {
  ContextReference,
  CreationMode,
  H3ReferenceBinding,
  H3ReferenceRole,
  StudioFlowNode,
  VideoReferenceMode,
} from "./studio-types";

type NodeComposerProps = {
  node: StudioFlowNode;
  generation?: Generation;
  generationHistory?: Generation[];
  providers: ProviderCapability[];
  assets: ProjectAsset[];
  contexts: ContextReference[];
  busy?: boolean;
  uploading?: boolean;
  style?: CSSProperties;
  onUpdate: (patch: Record<string, unknown>) => void;
  onUpload: (files: File[]) => void;
  onSelectAsset: (asset: ProjectAsset) => void;
  onRun: () => void;
  onRetry?: () => void;
  onCancel?: () => void;
  onDelete: () => void;
  onSelectGeneration?: (generationId: string) => void;
};

type ComposerSelectOption = {
  value: string;
  label?: string;
};

type ComposerSelectProps = {
  label: string;
  value: string;
  options: ComposerSelectOption[];
  wide?: boolean;
  disabled?: boolean;
  onValueChange: (value: string) => void;
};

function ComposerSelect({ label, value, options, wide = false, disabled = false, onValueChange }: ComposerSelectProps) {
  const selectedLabel = options.find((option) => option.value === value)?.label ?? value;
  return (
    <label className={"composer-option " + (wide ? "composer-option--wide" : "")}>
      <span>{label}</span>
      <Select disabled={disabled} value={value} onValueChange={(nextValue) => nextValue && onValueChange(String(nextValue))}>
        <SelectTrigger size="sm" className="composer-select-trigger" aria-label={label} title={selectedLabel}>
          <SelectValue>{selectedLabel}</SelectValue>
        </SelectTrigger>
        <SelectContent align="start">
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label ?? option.value}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

export function NodeComposer({ node, generation, generationHistory = [], providers, assets, contexts, busy: busyProp = false, uploading = false, style, onUpdate, onUpload, onSelectAsset, onRun, onRetry, onCancel, onDelete, onSelectGeneration }: NodeComposerProps) {
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const config = node.data.config;
  const mode = creationMode(config);
  const definition = mode ? creationModes[mode] : null;
  const prompt = textConfig(config, "prompt", "");
  const busy = busyProp || generation?.status === "queued" || generation?.status === "running";
  const failed = generation?.status === "failed";
  const allModelProviders = mode === "text" || mode === "image" || mode === "video"
    ? providers.filter((provider) => provider.kind === mode)
    : [];
  const configuredProviderId = textConfig(config, "provider", "");
  const configuredModel = textConfig(config, "model", "");
  // Keep the node's current provider visible when it is not configured so a
  // saved draft never silently falls back to Mock. New selections only show
  // configured providers (plus Mock as a safe no-key fallback).
  const modelProviders = allModelProviders.filter((provider) => (
    provider.configured || provider.id === "mock" || provider.id === configuredProviderId
  ));
  const activeProvider = modelProviders.find((provider) => (
    provider.id === configuredProviderId
    && (!configuredModel || provider.models.includes(configuredModel))
  )) ?? modelProviders.find((provider) => provider.models.includes(configuredModel))
    ?? modelProviders.find((provider) => provider.configured && provider.id !== "mock")
    ?? modelProviders[0];
  const selectedActiveModel = configuredModel && activeProvider?.models.includes(configuredModel)
    ? configuredModel
    : activeProvider?.model ?? definition?.models[0] ?? "";
  const activeModel = mode === "image"
    && activeProvider?.id === "qwen"
    && contexts.some((context) => context.kind === "image")
    && ["qwen-image-plus", "qwen-image"].includes(selectedActiveModel)
    ? "qwen-image-2.0-pro"
    : selectedActiveModel;
  const modelOptions = modelProviders.flatMap((provider) => (
    provider.models.map((model) => ({
      value: `${provider.id}::${model}`,
      label: `${provider.label} · ${model}${provider.id === "qwen" && model.startsWith("qwen-image-2.0") ? " · 支持参考图" : ""}${provider.configured ? "" : "（未配置）"}`,
    }))
  ));
  const modelSelectValue = activeProvider
    ? `${activeProvider.id}::${activeModel}`
    : activeModel;
  const isLocalH3 = mode === "video" && activeProvider?.id === "local_h3";
  const imageContexts = contexts.filter((context) => context.kind === "image" && context.imageUrl);
  const imageContextNodeIds = imageContexts.map((context) => context.nodeId);
  const referenceMode = videoReferenceMode(config);
  const intentPrompt = textConfig(config, "intent_prompt", prompt);
  const storedBindings = h3ReferenceBindings(config);
  const availableContextsByNodeId = new Map(imageContexts.map((context) => [context.nodeId, context]));
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
  const compiledPrompt = compileH3Ref2vaPrompt(
    intentPrompt,
    referenceBindings,
    textConfig(config, "camera_motion", "自动"),
  );
  const editorPrompt = isLocalH3 && referenceMode === "ref2va" ? intentPrompt : prompt;
  const promptMentions = Array.isArray(config.prompt_mentions)
    ? config.prompt_mentions.filter((item): item is MentionRef => (
      Boolean(item)
      && typeof item === "object"
      && ["asset", "node", "shot", "generation"].includes(String((item as Record<string, unknown>).type))
      && typeof (item as Record<string, unknown>).id === "string"
      && typeof (item as Record<string, unknown>).label === "string"
    ))
    : [];
  const mentionOptions = [
    ...contexts.map((context) => ({
      type: "node" as const,
      id: context.nodeId,
      label: context.title,
      kind: context.kind,
      subtitle: context.source === "upload" ? "已上传参考" : "画布节点",
    })),
    ...assets.map((asset) => ({
      type: "asset" as const,
      id: asset.id,
      label: asset.filename,
      kind: asset.kind,
      subtitle: `${asset.role === "last_frame" ? "视频末帧 · " : ""}${asset.kind === "video" ? "视频" : asset.kind === "audio" ? "音频" : "图片"}`,
    })),
  ] satisfies MentionOption[];
  const firstFrameNodeId = frameNodeSelection(
    config,
    "first_frame_node_id",
    "",
    imageContextNodeIds,
  );
  const lastFrameNodeId = frameNodeSelection(
    config,
    "last_frame_node_id",
    "",
    imageContextNodeIds,
  );
  const frameOptions = [
    { value: "__none__", label: "不使用" },
    ...imageContexts.map((context, index) => ({
      value: context.nodeId,
      label: `图片 ${index + 1}`,
    })),
  ];
  const providerSupportsImageReference = mode !== "image"
    || imageContexts.length === 0
    || activeProvider?.id === "qwen"
    || activeProvider?.id === "google_genai";
  const providerReady = (!["text", "image", "video"].includes(mode ?? "")
    || Boolean(activeProvider?.configured))
    && providerSupportsImageReference;
  const uploadEnabled = !busy && !uploading && (!mode || mode === "image" || mode === "video");
  const runnablePrompt = isLocalH3 && referenceMode === "ref2va" ? compiledPrompt : prompt;
  const referenceModeError = referenceMode === "ref2va"
    ? referenceBindings.length === 0
      ? "全参考模式至少需要 1 张图片"
      : compiledPrompt.length > 8000
        ? `编译后的 Prompt 为 ${compiledPrompt.length} 字，超过 H3 的 8000 字限制`
        : null
    : null;
  const referenceModeReady = referenceModeError === null;

  const updateReferenceBindings = (nextBindings: H3ReferenceBinding[]) => {
    const normalized = nextBindings.map((binding, index) => ({ ...binding, order: index + 1 }));
    onUpdate({
      reference_bindings: serializeH3ReferenceBindings(normalized),
      compiled_prompt: compileH3Ref2vaPrompt(
        intentPrompt,
        normalized,
        textConfig(config, "camera_motion", "自动"),
      ),
      prompt_schema: "h3_ref2va_v1",
    });
  };

  const selectReferenceMode = (nextMode: VideoReferenceMode) => {
    if (nextMode === "ref2va") {
      onUpdate({
        video_reference_mode: nextMode,
        first_frame_node_id: "",
        last_frame_node_id: "",
        intent_prompt: intentPrompt,
        reference_bindings: serializeH3ReferenceBindings(referenceBindings),
        compiled_prompt: compiledPrompt,
        prompt_schema: "h3_ref2va_v1",
      });
      return;
    }
    onUpdate({
      video_reference_mode: nextMode,
      ...(nextMode === "text" ? { first_frame_node_id: "", last_frame_node_id: "" } : {}),
    });
  };

  const selectMode = (nextMode: CreationMode) => {
    const nextDefinition = creationModes[nextMode];
    // Qwen is the default image model. Keep this preference explicit instead
    // of relying on the provider API's ordering (which also includes Mock and
    // any legacy image providers).
    const nextProvider = nextMode === "image"
      ? providers.find((provider) => provider.kind === "image" && provider.id === "qwen" && provider.configured)
        ?? providers.find((provider) => provider.kind === "image" && provider.id === "qwen")
        ?? providers.find((provider) => provider.kind === nextMode && provider.configured && provider.id !== "mock")
        ?? providers.find((provider) => provider.kind === nextMode)
      : providers.find((provider) => (
        provider.kind === nextMode && provider.configured && provider.id !== "mock"
      )) ?? providers.find((provider) => provider.kind === nextMode);
    onUpdate({
      mode: nextMode,
      provider: nextProvider?.id,
      model: nextProvider?.model ?? nextDefinition.models[0],
      aspect_ratio: textConfig(config, "aspect_ratio", "16:9"),
      resolution: nextMode === "video" && nextProvider?.id === "local_h3"
        ? "256P"
        : textConfig(config, "resolution", "2K"),
      quality: textConfig(config, "quality", "标准"),
      count: numberConfig(config, "count", 1),
      ...(nextMode === "video" && nextProvider?.id === "local_h3"
        ? {
            preset: "custom",
            width: 256,
            height: 256,
            duration_seconds: 1,
            steps: 4,
            video_reference_mode: "text",
          }
        : {}),
    });
  };

  return (
    <section className={`node-composer ${busy ? "is-busy" : ""} ${isLocalH3 && referenceMode === "ref2va" ? "is-ref2va" : ""}`} style={style} aria-label="节点创作控制台" aria-busy={busy || undefined}>
      <header className="node-composer__header">
        <Tabs
          value={mode ?? ""}
          onValueChange={(value) => selectMode(value as CreationMode)}
          className="node-composer__tabs"
        >
          <TabsList variant="line" aria-label="生成类型">
            {visibleCreationModeOrder.map((item) => {
              const ModeIcon = creationModes[item].icon;
              return (
                <TabsTrigger key={item} value={item} disabled={busy}>
                  <ModeIcon />
                  {creationModes[item].label}
                </TabsTrigger>
              );
            })}
          </TabsList>
        </Tabs>
        <div className="node-composer__identity">
          {(mode === "text" || mode === "image" || mode === "video") && activeProvider ? (
            <Badge variant={activeProvider.configured ? "outline" : "destructive"}>
              {activeProvider.configured
                ? `${activeProvider.label} · ${activeModel}`
                : `${activeProvider.label} 未配置`}
            </Badge>
          ) : null}
          <Badge variant="outline"><Sparkles />{node.id.slice(0, 8)}</Badge>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button type="button" variant="ghost" size="icon-sm" disabled={busy} aria-label="删除当前节点" onClick={onDelete} />
              }
            >
              <Trash2 />
            </TooltipTrigger>
            <TooltipContent>删除当前节点</TooltipContent>
          </Tooltip>
        </div>
      </header>

      <div className="node-composer__editor">
        <div className="node-composer__prompt-shell">
          <div className="composer-source-actions">
            <Button
              type="button"
              variant="ghost"
              className={uploading ? "is-uploading" : undefined}
              disabled={!uploadEnabled}
              title={mode === "text" || mode === "audio"
                ? "当前模式暂不支持图片参考"
                : "上传参考图片，支持 PNG、JPG、WebP、GIF，单张不超过 10MB"}
              onClick={() => uploadInputRef.current?.click()}
            >
              {uploading ? <LoaderCircle /> : <Upload />}<span>{uploading ? "上传中" : "上传"}</span>
            </Button>
            <input
              ref={uploadInputRef}
              className="composer-upload-input"
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              multiple
              tabIndex={-1}
              aria-hidden="true"
              onChange={(event) => {
                const files = Array.from(event.currentTarget.files ?? []);
                event.currentTarget.value = "";
                if (files.length === 0) return;
                if (!mode) selectMode("image");
                onUpload(files);
              }}
            />
            {assets.some((asset) => asset.kind === "image") ? (
              <Select
                value=""
                disabled={busy || uploading}
                onValueChange={(value) => {
                  const asset = assets.find((item) => item.id === value);
                  if (asset) onSelectAsset(asset);
                }}
              >
                <SelectTrigger size="sm" className="composer-asset-select" aria-label="从素材库选择">
                  <MousePointer2 /><SelectValue placeholder="选择" />
                </SelectTrigger>
                <SelectContent align="start">
                  {assets
                    .filter((asset) => asset.kind === "image")
                    .map((asset) => (
                      <SelectItem key={asset.id} value={asset.id}>
                        {asset.role === "last_frame" ? "末帧 · " : ""}{asset.filename}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            ) : (
              <Button type="button" variant="ghost" disabled title="项目素材库暂无可用图片">
                <MousePointer2 /><span>选择</span>
              </Button>
            )}
          </div>
          <Separator orientation="vertical" className="composer-source-separator" />
          <div className="composer-prompt-field">
            <MentionPicker
              wrapperClassName="node-composer__mention-picker"
              value={editorPrompt}
              options={mentionOptions}
              mentions={promptMentions}
              onMentionsChange={(mentions) => onUpdate({ prompt_mentions: mentions })}
              onMentionSelect={(option) => {
                if (option.type !== "asset") return;
                const asset = assets.find((item) => item.id === option.id);
                if (asset) onSelectAsset(asset);
              }}
              disabled={!mode || busy}
              placeholder={isLocalH3 && referenceMode === "ref2va"
                ? "描述目标镜头中的动作、运镜和节奏。参考素材的保留规则请在下方分别配置。"
                : definition?.placeholder ?? "先选择文本、图片、视频或音频生成"}
              onChange={(value) => {
                if (isLocalH3 && referenceMode === "ref2va") {
                  onUpdate({
                    intent_prompt: value,
                    compiled_prompt: compileH3Ref2vaPrompt(
                      value,
                      referenceBindings,
                      textConfig(config, "camera_motion", "自动"),
                    ),
                  });
                  return;
                }
                onUpdate({ prompt: value });
              }}
            />
            <div className="composer-prompt-meta">
              <span><Sparkles />{isLocalH3 && referenceMode === "ref2va" ? "镜头意图写在这里，素材规则在下方" : "用 @ 引用素材"}</span>
              <span>{editorPrompt.length} 字</span>
            </div>
          </div>
          {contexts.length > 0 ? (
            <div className="composer-context-strip" aria-label={`已引用 ${contexts.length} 个素材`}>
              <span className="composer-context-strip__label">参考素材</span>
              <div className="composer-context-strip__items">
                {contexts.map((context, index) => (
                  <div
                    className={`composer-context-card composer-context-card--${context.kind}`}
                    key={context.nodeId}
                    title={context.text ?? context.title}
                  >
                    {context.kind === "image" && context.imageUrl ? (
                      <img src={context.imageUrl} alt={`引用图片 ${index + 1}`} draggable={false} />
                    ) : <Type aria-hidden="true" />}
                    {context.source === "upload" && context.assetId ? (
                      <button
                        className="composer-context-card__remove"
                        type="button"
                        aria-label={`移除 ${context.title}`}
                        title="移除上传图片"
                        disabled={busy || uploading}
                        onClick={() => {
                          const remaining = uploadedAssets(config).filter((asset) => asset.id !== context.assetId);
                          const remainingBindings = referenceBindings.filter((binding) => binding.nodeId !== context.nodeId);
                          onUpdate({
                            uploaded_assets: remaining,
                            ...(textConfig(config, "first_frame_node_id", "") === context.nodeId
                              ? { first_frame_node_id: "" }
                              : {}),
                            ...(textConfig(config, "last_frame_node_id", "") === context.nodeId
                              ? { last_frame_node_id: "" }
                              : {}),
                            reference_bindings: serializeH3ReferenceBindings(remainingBindings),
                            compiled_prompt: compileH3Ref2vaPrompt(
                              intentPrompt,
                              remainingBindings,
                              textConfig(config, "camera_motion", "自动"),
                            ),
                          });
                        }}
                      >
                        <X aria-hidden="true" />
                      </button>
                    ) : null}
                    <span>
                      {context.source === "upload" ? "上传" : context.title}
                      {contexts.slice(0, index + 1).filter((item) => item.kind === context.kind).length}
                    </span>
                  </div>
                ))}
              </div>
              <span className="composer-context-strip__status">
                {uploading
                  ? "正在上传参考图…"
                  : isLocalH3 && referenceMode === "ref2va"
                  ? `全参考使用前 ${Math.min(imageContexts.length, 4)} 张 · 按 Picture 顺序注入`
                  : isLocalH3 && referenceMode === "keyframe"
                  ? `已连接 ${imageContexts.length} 张图片，可指定首尾帧`
                  : isLocalH3
                  ? "纯文本模式不会向 H3 传入图片"
                  : "将随提示词发送"}
              </span>
            </div>
          ) : null}
        </div>

        {isLocalH3 && referenceMode === "ref2va" ? (
          <section className="composer-ref2va" aria-label="H3 全参考素材定义">
            <header className="composer-ref2va__header">
              <div>
                <strong><Braces />Ref2VA 素材绑定</strong>
                <span>Picture 是传入顺序，Subject 是视频中持续追踪的对象</span>
              </div>
              <Badge variant={imageContexts.length > 4 ? "destructive" : "outline"}>
                {referenceBindings.length}/4 张
              </Badge>
            </header>
            {referenceBindings.length === 0 ? (
              <div className="composer-ref2va__empty">
                <Upload />上传图片或把图片节点连到当前视频节点，然后分别定义场景、角色或风格。
              </div>
            ) : (
              <div className="composer-ref2va__bindings">
                {referenceBindings.map((binding, index) => {
                  const context = imageContexts.find((item) => item.nodeId === binding.nodeId);
                  const updateBinding = (patch: Partial<H3ReferenceBinding>) => {
                    updateReferenceBindings(referenceBindings.map((item, itemIndex) => (
                      itemIndex === index ? { ...item, ...patch } : item
                    )));
                  };
                  const moveBinding = (direction: -1 | 1) => {
                    const nextIndex = index + direction;
                    if (nextIndex < 0 || nextIndex >= referenceBindings.length) return;
                    const next = [...referenceBindings];
                    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
                    updateReferenceBindings(next);
                  };
                  return (
                    <article className="composer-ref2va-card" key={binding.nodeId}>
                      <div className="composer-ref2va-card__media">
                        {context?.imageUrl ? <img src={context.imageUrl} alt={`Picture ${index + 1}`} draggable={false} /> : null}
                        <span>Picture {index + 1}</span>
                      </div>
                      <div className="composer-ref2va-card__identity">
                        <div className="composer-ref2va-card__subject">
                          <strong>{`<Subject ${index + 1}>`}</strong>
                          <div className="composer-ref2va-card__order">
                            <Button type="button" size="icon-xs" variant="ghost" disabled={busy || index === 0} aria-label="参考图上移" onClick={() => moveBinding(-1)}><ChevronUp /></Button>
                            <Button type="button" size="icon-xs" variant="ghost" disabled={busy || index === referenceBindings.length - 1} aria-label="参考图下移" onClick={() => moveBinding(1)}><ChevronDown /></Button>
                          </div>
                        </div>
                        <Select disabled={busy} value={binding.role} onValueChange={(value) => updateBinding({ role: value as H3ReferenceRole })}>
                          <SelectTrigger size="sm" aria-label={`Subject ${index + 1} 类型`}><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="scene">场景</SelectItem>
                            <SelectItem value="character">角色</SelectItem>
                            <SelectItem value="style">画风</SelectItem>
                            <SelectItem value="prop">道具</SelectItem>
                            <SelectItem value="effect">特效</SelectItem>
                          </SelectContent>
                        </Select>
                        <Input disabled={busy} value={binding.name} aria-label={`Subject ${index + 1} 名称`} placeholder="英文对象名称" onChange={(event) => updateBinding({ name: event.target.value })} />
                      </div>
                      <div className="composer-ref2va-card__rules">
                        <label>必须保留<Input disabled={busy} value={binding.preserve} placeholder="identity, costume, materials..." onChange={(event) => updateBinding({ preserve: event.target.value })} /></label>
                        <label>允许改变<Input disabled={busy} value={binding.mutable} placeholder="pose, camera angle, scale..." onChange={(event) => updateBinding({ mutable: event.target.value })} /></label>
                        <label>禁止复制<Input disabled={busy} value={binding.exclude} placeholder="watermark, arrows, sheet layout..." onChange={(event) => updateBinding({ exclude: event.target.value })} /></label>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
            {imageContexts.length > 4 ? <p className="composer-ref2va__warning">P0 最多使用 4 张素材；其余图片不会传给 H3。</p> : null}
            <Collapsible className="composer-ref2va-preview">
              <CollapsibleTrigger disabled={!compiledPrompt}><Braces />查看编译后的 H3 Prompt</CollapsibleTrigger>
              <CollapsibleContent>
                <Textarea readOnly value={compiledPrompt} aria-label="编译后的 H3 Ref2VA Prompt" />
              </CollapsibleContent>
            </Collapsible>
          </section>
        ) : null}

        {mode && definition ? (
          <>
            <Separator className="composer-divider" />
            <div className="composer-options">
              <div className="composer-options__controls">
              <ComposerSelect
                label="模型"
                value={modelOptions.length > 0 ? modelSelectValue : activeModel}
                options={modelOptions.length > 0
                  ? modelOptions
                  : definition.models.map((value) => ({ value }))}
                wide
                disabled={busy}
                onValueChange={(value) => {
                  const [provider, model] = value.includes("::")
                    ? value.split("::", 2)
                    : [undefined, value];
                  onUpdate({ provider, model });
                }}
              />

              {(mode === "image" || (mode === "video" && !isLocalH3)) ? (
                <ComposerSelect
                  label="画幅"
                  value={textConfig(config, "aspect_ratio", "16:9")}
                  options={aspectRatios.map((value) => ({ value }))}
                  disabled={busy}
                  onValueChange={(aspect_ratio) => onUpdate({ aspect_ratio })}
                />
              ) : null}

              {(mode === "image" || mode === "video") ? (
                <ComposerSelect
                  label={isLocalH3 ? "输出尺寸" : "清晰度"}
                  value={isLocalH3
                    ? (textConfig(config, "preset", "custom") === "preview"
                      ? "preview"
                      : String(numberConfig(config, "width", 256) === 1280 ? 720 : numberConfig(config, "width", 256)))
                    : textConfig(config, "resolution", "2K")}
                  options={isLocalH3 ? localVideoSizes : resolutions.map((value) => ({ value }))}
                  disabled={busy}
                  onValueChange={(resolution) => {
                    if (!isLocalH3) {
                      onUpdate({ resolution });
                      return;
                    }
                    if (resolution === "preview") {
                      onUpdate({ preset: "preview", resolution: "PREVIEW" });
                      return;
                    }
                    const size = Number(resolution);
                    onUpdate(size === 720
                      ? { preset: "720p", width: 1280, height: 720, resolution: "720P" }
                      : { preset: "custom", width: size, height: size, resolution: `${size}P` });
                  }}
                />
              ) : null}

              {(mode === "image" || (mode === "video" && !isLocalH3)) ? (
                <ComposerSelect
                  label="质量"
                  value={textConfig(config, "quality", "标准")}
                  options={qualityLevels.map((value) => ({ value }))}
                  disabled={busy}
                  onValueChange={(quality) => onUpdate({ quality })}
                />
              ) : null}

              {mode === "text" ? (
                <ComposerSelect
                  label="篇幅"
                  value={textConfig(config, "output_length", "中等")}
                  options={["简短", "中等", "详细"].map((value) => ({ value }))}
                  disabled={busy}
                  onValueChange={(output_length) => onUpdate({ output_length })}
                />
              ) : null}

              {mode === "text" ? (
                <ComposerSelect
                  label="创造性"
                  value={String(numberConfig(config, "temperature", 0.7))}
                  options={[
                    { value: "0.2", label: "准确" },
                    { value: "0.7", label: "平衡" },
                    { value: "1", label: "自由" },
                  ]}
                  disabled={busy}
                  onValueChange={(temperature) => onUpdate({ temperature: Number(temperature) })}
                />
              ) : null}

              {mode === "video" ? (
                <ComposerSelect
                  label="时长"
                  value={String(numberConfig(config, "duration_seconds", 5))}
                  options={[1, 2, 4, 5, 6, 8, 10].map((value) => ({ value: String(value), label: String(value) + " 秒" }))}
                  disabled={busy}
                  onValueChange={(duration_seconds) => onUpdate({ duration_seconds: Number(duration_seconds) })}
                />
              ) : null}

              {isLocalH3 ? (
                <ComposerSelect
                  label="参考模式"
                  value={referenceMode}
                  options={[
                    { value: "text", label: "纯文本" },
                    { value: "keyframe", label: "首尾帧" },
                    { value: "ref2va", label: "全参考 Ref2VA" },
                  ]}
                  wide
                  disabled={busy}
                  onValueChange={(value) => selectReferenceMode(value as VideoReferenceMode)}
                />
              ) : null}

              {isLocalH3 && referenceMode === "keyframe" ? (
                <ComposerSelect
                  label="首帧"
                  value={firstFrameNodeId || "__none__"}
                  options={frameOptions}
                  disabled={busy || imageContexts.length === 0}
                  onValueChange={(value) => onUpdate({
                    first_frame_node_id: value === "__none__" ? "" : value,
                  })}
                />
              ) : null}

              {isLocalH3 && referenceMode === "keyframe" ? (
                <ComposerSelect
                  label="尾帧"
                  value={lastFrameNodeId || "__none__"}
                  options={frameOptions}
                  disabled={busy || imageContexts.length === 0}
                  onValueChange={(value) => onUpdate({
                    last_frame_node_id: value === "__none__" ? "" : value,
                  })}
                />
              ) : null}

              {mode === "video" ? (
                <ComposerSelect
                  label="镜头运动"
                  value={textConfig(config, "camera_motion", "自动")}
                  options={["自动", "固定机位", "推进", "拉远", "横移", "跟拍", "环绕"].map((value) => ({ value }))}
                  wide
                  disabled={busy}
                  onValueChange={(camera_motion) => onUpdate({
                    camera_motion,
                    ...(isLocalH3 && referenceMode === "ref2va" ? {
                      compiled_prompt: compileH3Ref2vaPrompt(intentPrompt, referenceBindings, camera_motion),
                    } : {}),
                  })}
                />
              ) : null}

              {mode === "audio" ? (
                <ComposerSelect
                  label="声音类型"
                  value={textConfig(config, "voice", "自然旁白")}
                  options={["自然旁白", "电影预告", "青年角色", "儿童角色", "环境音效"].map((value) => ({ value }))}
                  wide
                  disabled={busy}
                  onValueChange={(voice) => onUpdate({ voice })}
                />
              ) : null}

              {mode === "audio" ? (
                <ComposerSelect
                  label="情绪"
                  value={textConfig(config, "emotion", "自然")}
                  options={["自然", "克制", "温暖", "紧张", "激昂"].map((value) => ({ value }))}
                  disabled={busy}
                  onValueChange={(emotion) => onUpdate({ emotion })}
                />
              ) : null}

              {mode !== "text" && !isLocalH3 ? (
                <ComposerSelect
                  label="数量"
                  value={String(numberConfig(config, "count", 1))}
                  options={[1, 2, 3, 4].map((value) => ({ value: String(value), label: String(value) + " 个" }))}
                  disabled={busy}
                  onValueChange={(count) => onUpdate({ count: Number(count) })}
                />
              ) : null}

              {mode === "image" ? (
                <label className="composer-switch">
                  <span>全景</span>
                  <Switch
                    size="sm"
                    checked={booleanConfig(config, "panorama", false)}
                    disabled={busy}
                    onCheckedChange={(panorama) => onUpdate({ panorama })}
                  />
                </label>
              ) : null}
              </div>

              <Tooltip>
                  <TooltipTrigger
                    render={
                    <Button
                      className="composer-run"
                      type="button"
                      size="icon-lg"
                      disabled={busy ? !onCancel : !runnablePrompt.trim() || !providerReady || !referenceModeReady}
                      aria-label={busy ? "取消生成" : failed ? "重试生成" : "运行当前节点"}
                      onClick={busy ? onCancel : failed ? onRetry : onRun}
                    />
                  }
                >
                  {busy ? <Square /> : failed ? <RefreshCw /> : <ArrowUp />}
                </TooltipTrigger>
                <TooltipContent>
                  {busy
                    ? "取消当前生成任务"
                    : failed
                      ? "重试当前生成任务"
                      : providerReady
                    ? referenceModeReady
                      ? "运行当前生成节点"
                      : referenceModeError
                    : !providerSupportsImageReference
                      ? "当前图片模型不支持参考图，请选择千问或 Gemini 图片模型"
                      : "请先在后端配置所选模型的 API Key"}
                </TooltipContent>
              </Tooltip>
            </div>

            {generationHistory.length > 1 ? (
              <ComposerSelect
                label="版本"
                value={generation?.id ?? generationHistory[0]?.id ?? ""}
                options={generationHistory.map((item, index) => ({
                  value: item.id,
                  label: `第 ${generationHistory.length - index} 次 · ${item.status === "succeeded" ? "完成" : item.status === "failed" ? "失败" : "处理中"}`,
                }))}
                disabled={busy}
                onValueChange={(value) => onSelectGeneration?.(value)}
              />
            ) : null}

            {(mode === "image" || mode === "video") ? (
              <Collapsible className="composer-advanced">
                <CollapsibleTrigger disabled={busy}><SlidersHorizontal />高级参数</CollapsibleTrigger>
                <CollapsibleContent className="composer-advanced__content">
                  <label>排除内容
                    <Input
                      disabled={busy}
                      value={textConfig(config, "negative_prompt", "")}
                      placeholder="不希望出现在结果中的元素"
                      onChange={(event) => onUpdate({ negative_prompt: event.target.value })}
                    />
                  </label>
                  <label>随机种子
                    <Input
                      disabled={busy}
                      type="number"
                      value={numberConfig(config, "seed", -1)}
                      onChange={(event) => onUpdate({ seed: Number(event.target.value) })}
                    />
                  </label>
                  {isLocalH3 ? (
                    <label>推理步数
                      <Input
                        disabled={busy}
                        type="number"
                        min={1}
                        max={50}
                        value={numberConfig(config, "steps", 4)}
                        onChange={(event) => onUpdate({ steps: Number(event.target.value) })}
                      />
                    </label>
                  ) : null}
                </CollapsibleContent>
              </Collapsible>
            ) : null}
          </>
        ) : (
          <div className="composer-empty-hint">
            <Sparkles />先选择文本、图片或视频。
          </div>
        )}
      </div>
    </section>
  );
}
