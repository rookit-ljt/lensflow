"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, KeyRound, LoaderCircle, Settings2, TriangleAlert, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type RuntimeSettings, type RuntimeSettingsPayload } from "@/lib/api";

type LlmSettingsProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: () => void;
};

type SettingsKind = "text" | "image";

const defaults = {
  provider: "qwen" as RuntimeSettingsPayload["provider"],
  textModel: "qwen3.7-plus",
  imageModel: "qwen-image-plus",
  textBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  imageBaseUrl: "https://dashscope.aliyuncs.com/api/v1",
};

export function LlmSettings({ open, onOpenChange, onSaved }: LlmSettingsProps) {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [kind, setKind] = useState<SettingsKind>("text");
  const [provider, setProvider] = useState<RuntimeSettingsPayload["provider"]>(defaults.provider);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(defaults.textModel);
  const [baseUrl, setBaseUrl] = useState(defaults.textBaseUrl);
  const [applyToAgent, setApplyToAgent] = useState(true);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setMessage(null);
    setLoading(true);
    void api.getRuntimeSettings()
      .then((value) => {
        setSettings(value);
        const nextProvider = value.qwen_configured || value.agent_provider === "qwen" ? "qwen" : "openai_compatible";
        setProvider(nextProvider);
        setModel(kind === "text" ? (nextProvider === "qwen" ? value.qwen_text_model : value.text_model) : (nextProvider === "qwen" ? value.qwen_image_model : value.image_model));
        setBaseUrl(kind === "text" ? (nextProvider === "qwen" ? value.qwen_text_base_url : value.text_base_url) : (nextProvider === "qwen" ? value.qwen_image_base_url : value.image_base_url));
      })
      .catch((cause) => setMessage({ type: "error", text: cause instanceof Error ? cause.message : "读取模型配置失败" }))
      .finally(() => setLoading(false));
  }, [open]);

  const configured = useMemo(() => {
    if (!settings) return false;
    if (kind === "text") return provider === "qwen" ? settings.qwen_configured : settings.text_configured;
    return provider === "qwen" ? settings.qwen_image_configured : settings.image_configured;
  }, [kind, provider, settings]);

  const selectKind = (nextKind: SettingsKind) => {
    setKind(nextKind);
    setMessage(null);
    if (!settings) return;
    const nextProvider = provider;
    setModel(nextKind === "text" ? (nextProvider === "qwen" ? settings.qwen_text_model : settings.text_model) : (nextProvider === "qwen" ? settings.qwen_image_model : settings.image_model));
    setBaseUrl(nextKind === "text" ? (nextProvider === "qwen" ? settings.qwen_text_base_url : settings.text_base_url) : (nextProvider === "qwen" ? settings.qwen_image_base_url : settings.image_base_url));
  };

  const selectProvider = (nextProvider: RuntimeSettingsPayload["provider"]) => {
    setProvider(nextProvider);
    setApiKey("");
    if (!settings) return;
    setModel(kind === "text" ? (nextProvider === "qwen" ? settings.qwen_text_model : settings.text_model) : (nextProvider === "qwen" ? settings.qwen_image_model : settings.image_model));
    setBaseUrl(kind === "text" ? (nextProvider === "qwen" ? settings.qwen_text_base_url : settings.text_base_url) : (nextProvider === "qwen" ? settings.qwen_image_base_url : settings.image_base_url));
  };

  const payload = (): RuntimeSettingsPayload => ({
    provider,
    kind,
    api_key: apiKey,
    model,
    base_url: baseUrl,
    apply_to_agent: kind === "text" && applyToAgent,
  });

  const save = async (shouldTest = false) => {
    setMessage(null);
    if (!model.trim()) {
      setMessage({ type: "error", text: "请先填写模型名称" });
      return;
    }
    if (!apiKey.trim() && !configured) {
      setMessage({ type: "error", text: "首次配置需要填写 API Key" });
      return;
    }
    if (shouldTest) setTesting(true); else setLoading(true);
    try {
      if (shouldTest) {
        const result = await api.testRuntimeSettings(payload());
        setMessage({ type: result.ok ? "success" : "error", text: result.message });
        return;
      }
      const next = await api.updateRuntimeSettings(payload());
      setSettings(next);
      setApiKey("");
      setMessage({ type: "success", text: "配置已保存，当前 API 进程立即生效。" });
      onSaved?.();
    } catch (cause) {
      setMessage({ type: "error", text: cause instanceof Error ? cause.message : "配置保存失败" });
    } finally {
      setLoading(false);
      setTesting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="模型设置">
      <Card className="w-full max-w-xl border-white/10 bg-zinc-950/95 text-zinc-100 shadow-2xl shadow-black/50">
        <CardHeader className="border-b border-white/10 pb-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-xl"><Settings2 className="size-5 text-cyan-300" />模型设置</CardTitle>
              <CardDescription className="mt-2 text-zinc-400">本地开发快速配置。Key 只写入本机 .env，不会回显到页面或项目数据。</CardDescription>
            </div>
            <Button variant="ghost" size="icon" aria-label="关闭设置" onClick={() => onOpenChange(false)}><X /></Button>
          </div>
          <div className="mt-4 flex gap-2 rounded-xl bg-white/[0.04] p-1">
            {(["text", "image"] as const).map((item) => (
              <Button key={item} type="button" variant={kind === item ? "secondary" : "ghost"} className="flex-1" onClick={() => selectKind(item)}>
                {item === "text" ? "文本模型" : "图片模型"}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="space-y-5 pt-5">
          {!settings?.runtime_enabled && !loading ? (
            <div className="flex gap-3 rounded-xl border border-amber-300/20 bg-amber-300/10 p-3 text-sm text-amber-100"><TriangleAlert className="mt-0.5 size-4 shrink-0" /><span>运行时设置只在 development 环境开放，请改用部署环境的 Secret 管理。</span></div>
          ) : null}
          <div className="flex items-center justify-between">
            <div><p className="font-medium">{kind === "text" ? "文本 / Agent" : "图片生成"}</p><p className="text-xs text-zinc-500">{configured ? "当前已配置，可留空 Key 仅更新模型" : "尚未配置"}</p></div>
            <Badge variant={configured ? "secondary" : "outline"} className={configured ? "text-emerald-300" : "text-zinc-400"}>{configured ? <><CheckCircle2 />已配置</> : "待配置"}</Badge>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="settings-provider">服务商</Label><select id="settings-provider" className="h-8 w-full rounded-2xl border border-white/10 bg-white/[0.06] px-3 text-sm outline-none focus:ring-2 focus:ring-cyan-300/30" value={provider} onChange={(event) => selectProvider(event.target.value as RuntimeSettingsPayload["provider"])}><option value="qwen">阿里云百炼 · 千问</option><option value="openai_compatible">OpenAI Compatible</option></select></div>
            <div className="space-y-2"><Label htmlFor="settings-model">模型名称</Label><Input id="settings-model" value={model} onChange={(event) => setModel(event.target.value)} placeholder={kind === "text" ? defaults.textModel : defaults.imageModel} /></div>
          </div>
          <div className="space-y-2"><Label htmlFor="settings-key"><KeyRound className="size-4 text-zinc-400" />API Key</Label><Input id="settings-key" type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={configured ? "已配置（留空保持不变）" : "粘贴服务商 API Key"} /></div>
          <div className="space-y-2"><Label htmlFor="settings-base-url">Base URL</Label><Input id="settings-base-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder={kind === "text" ? defaults.textBaseUrl : defaults.imageBaseUrl} /></div>
          {kind === "text" ? <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-300"><input type="checkbox" checked={applyToAgent} onChange={(event) => setApplyToAgent(event.target.checked)} className="size-4 accent-cyan-300" />同步给 Chat Agent 使用</label> : <p className="text-xs text-zinc-500">图片模型不会在这里发起真实请求，避免测试产生费用；保存后可在图片节点中验证。</p>}
          {message ? <div className={`rounded-xl border p-3 text-sm ${message.type === "success" ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-200" : "border-red-300/20 bg-red-300/10 text-red-200"}`}>{message.text}</div> : null}
          <div className="flex flex-col-reverse gap-2 border-t border-white/10 pt-4 sm:flex-row sm:justify-end">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>
            {kind === "text" ? <Button type="button" variant="outline" disabled={loading || testing} onClick={() => void save(true)}>{testing ? <LoaderCircle className="animate-spin" /> : null}测试连接</Button> : null}
            <Button type="button" disabled={loading || testing || !settings?.runtime_enabled} onClick={() => void save(false)}>{loading ? <LoaderCircle className="animate-spin" /> : null}保存配置</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
