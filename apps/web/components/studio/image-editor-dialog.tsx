"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  Crop,
  Download,
  Eye,
  EyeOff,
  FlipHorizontal,
  FlipVertical,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Plus,
  RefreshCw,
  RotateCcw,
  RotateCw,
  SlidersHorizontal,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ProjectAsset } from "@/lib/api";

export type AspectRatioPreset = "free" | "16:9" | "9:16" | "1:1" | "4:3" | "3:4" | "21:9";

const PRESET_RATIOS: Record<AspectRatioPreset, number | null> = {
  free: null,
  "16:9": 16 / 9,
  "9:16": 9 / 16,
  "1:1": 1,
  "4:3": 4 / 3,
  "3:4": 3 / 4,
  "21:9": 21 / 9,
};

const PRESET_LABELS: Record<AspectRatioPreset, { label: string; desc: string }> = {
  free: { label: "自由", desc: "任意拖拽无固定比例" },
  "16:9": { label: "16:9", desc: "影视横屏 / 视频标准" },
  "9:16": { label: "9:16", desc: "短视频 / 手机全屏" },
  "1:1": { label: "1:1", desc: "正方形 / 头像素材" },
  "4:3": { label: "4:3", desc: "经典画幅 / 摄影" },
  "3:4": { label: "3:4", desc: "经典竖屏 / 人像" },
  "21:9": { label: "21:9", desc: "宽银幕电影" },
};

type CropRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type ImageEditorDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  imageUrl: string;
  title?: string;
  nodeId?: string | null;
  onSaveAsAsset: (file: File, meta: { width: number; height: number; aspectRatio: number }) => Promise<ProjectAsset | void>;
  onUpdateNodeImage?: (nodeId: string, asset: ProjectAsset, aspectRatio: number) => Promise<void>;
  onCreateDerivedNode?: (sourceNodeId: string, asset: ProjectAsset, aspectRatio: number) => Promise<void>;
};

export function ImageEditorDialog({
  open,
  onOpenChange,
  imageUrl,
  title = "图片编辑",
  nodeId,
  onSaveAsAsset,
  onUpdateNodeImage,
  onCreateDerivedNode,
}: ImageEditorDialogProps) {
  // 原始图像与尺寸
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 变换状态
  const [rotation, setRotation] = useState<number>(0); // 0, 90, 180, 270
  const [flipH, setFlipH] = useState<boolean>(false);
  const [flipV, setFlipV] = useState<boolean>(false);

  // 裁剪与比例
  const [aspectPreset, setAspectPreset] = useState<AspectRatioPreset>("free");
  const [crop, setCrop] = useState<CropRect>({ x: 0, y: 0, width: 100, height: 100 }); // 百分比 (0 - 100)

  // 抠图状态
  const [isMattingActive, setIsMattingActive] = useState<boolean>(false);
  const [isMattingProcessing, setIsMattingProcessing] = useState<boolean>(false);
  const [tolerance, setTolerance] = useState<number>(38); // 容差阈值 10 - 100
  const [smoothness, setSmoothness] = useState<number>(2); // 边缘羽化 0 - 6
  const [showOriginal, setShowOriginal] = useState<boolean>(false); // 对比原图

  // 保存与导出状态
  const [savingAction, setSavingAction] = useState<string | null>(null);
  const [isDownloaded, setIsDownloaded] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // 容器与引用
  const containerRef = useRef<HTMLDivElement>(null);
  const sourceImageRef = useRef<HTMLImageElement | null>(null);
  const mattedCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);

  // 重置所有状态
  const handleReset = useCallback(() => {
    setRotation(0);
    setFlipH(false);
    setFlipV(false);
    setAspectPreset("free");
    setCrop({ x: 0, y: 0, width: 100, height: 100 });
    setIsMattingActive(false);
    setTolerance(38);
    setSmoothness(2);
    setShowOriginal(false);
  }, []);

  // 加载图片
  useEffect(() => {
    if (!open || !imageUrl) return;
    setImageLoaded(false);
    setLoadError(null);
    handleReset();

    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      sourceImageRef.current = img;
      setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight });
      setImageLoaded(true);
    };
    img.onerror = () => {
      // 尝试不用 crossOrigin 再次加载
      const fallbackImg = new Image();
      fallbackImg.onload = () => {
        sourceImageRef.current = fallbackImg;
        setNaturalSize({ width: fallbackImg.naturalWidth, height: fallbackImg.naturalHeight });
        setImageLoaded(true);
      };
      fallbackImg.onerror = () => {
        setLoadError("无法加载图片资源，请检查图片路径是否有效。");
      };
      fallbackImg.src = imageUrl;
    };
    img.src = imageUrl;
  }, [open, imageUrl, handleReset]);

  // 根据当前变换（旋转与翻转）获取实际渲染尺寸
  const transformedSize = useMemo(() => {
    if (!naturalSize) return { width: 1, height: 1 };
    const isRotated = rotation === 90 || rotation === 270;
    return {
      width: isRotated ? naturalSize.height : naturalSize.width,
      height: isRotated ? naturalSize.width : naturalSize.height,
    };
  }, [naturalSize, rotation]);

  // 比例切换时，自动居中调整裁剪框
  const applyPresetRatio = useCallback((preset: AspectRatioPreset) => {
    setAspectPreset(preset);
    const targetRatio = PRESET_RATIOS[preset];
    if (!targetRatio) return;

    const { width: imgW, height: imgH } = transformedSize;
    const currentImgRatio = imgW / imgH;

    let newW = 100;
    let newH = 100;

    if (targetRatio >= currentImgRatio) {
      // 目标比原图更宽：高度变小
      newW = 100;
      newH = (currentImgRatio / targetRatio) * 100;
    } else {
      // 目标比原图更窄：宽度变小
      newH = 100;
      newW = (targetRatio / currentImgRatio) * 100;
    }

    const newX = (100 - newW) / 2;
    const newY = (100 - newH) / 2;
    setCrop({
      x: Math.max(0, newX),
      y: Math.max(0, newY),
      width: Math.min(100, newW),
      height: Math.min(100, newH),
    });
  }, [transformedSize]);

  // 纯前端智能去背景算法
  const performMatting = useCallback(() => {
    const img = sourceImageRef.current;
    if (!img || !naturalSize) return;

    setIsMattingProcessing(true);

    try {
      // 创建离屏 Canvas 并绘制当前旋转镜像状态下的图像
      const { width: origW, height: origH } = naturalSize;
      const offscreen = document.createElement("canvas");
      offscreen.width = origW;
      offscreen.height = origH;
      const ctx = offscreen.getContext("2d", { willReadFrequently: true });
      if (!ctx) throw new Error("无法初始化 Canvas 绘图上下文");

      ctx.drawImage(img, 0, 0);

      // 读取原始像素数据
      const imgData = ctx.getImageData(0, 0, origW, origH);
      const data = imgData.data;

      // 采样背景色：采样 4 个角和四条边中间的像素
      const samplePoints = [
        [0, 0],
        [origW - 1, 0],
        [0, origH - 1],
        [origW - 1, origH - 1],
        [Math.floor(origW / 2), 0],
        [0, Math.floor(origH / 2)],
        [origW - 1, Math.floor(origH / 2)],
        [Math.floor(origW / 2), origH - 1],
      ];

      const bgColors: [number, number, number][] = [];
      for (const [sx, sy] of samplePoints) {
        const idx = (sy * origW + sx) * 4;
        bgColors.push([data[idx], data[idx + 1], data[idx + 2]]);
      }

      // 计算平均背景色
      let avgR = 0, avgG = 0, avgB = 0;
      for (const [r, g, b] of bgColors) {
        avgR += r;
        avgG += g;
        avgB += b;
      }
      avgR /= bgColors.length;
      avgG /= bgColors.length;
      avgB /= bgColors.length;

      const tolSq = tolerance * tolerance * 3.2;
      const featherSq = (tolerance + smoothness * 6) * (tolerance + smoothness * 6) * 3.2;

      // 逐像素处理透明度
      const totalPixels = origW * origH;
      for (let i = 0; i < totalPixels; i++) {
        const offset = i * 4;
        const r = data[offset];
        const g = data[offset + 1];
        const b = data[offset + 2];

        // 计算与背景候选样本的最小颜色距离
        let minDiffSq = Infinity;
        for (const [bgr, bgg, bgb] of bgColors) {
          const dr = r - bgr;
          const dg = g - bgg;
          const db = b - bgb;
          // 加权感知色差 (2*dr^2 + 4*dg^2 + 3*db^2)
          const diff = 2 * dr * dr + 4 * dg * dg + 3 * db * db;
          if (diff < minDiffSq) minDiffSq = diff;
        }

        // 计算与平均背景色的距离
        const drAvg = r - avgR;
        const dgAvg = g - avgG;
        const dbAvg = b - avgB;
        const diffAvg = 2 * drAvg * drAvg + 4 * dgAvg * dgAvg + 3 * dbAvg * dbAvg;
        if (diffAvg < minDiffSq) minDiffSq = diffAvg;

        if (minDiffSq <= tolSq) {
          // 完全背景
          data[offset + 3] = 0;
        } else if (minDiffSq < featherSq && smoothness > 0) {
          // 边缘羽化过渡带
          const factor = (minDiffSq - tolSq) / (featherSq - tolSq);
          data[offset + 3] = Math.round(data[offset + 3] * Math.max(0, Math.min(1, factor)));
        }
      }

      // 回写抠图后数据
      ctx.putImageData(imgData, 0, 0);
      mattedCanvasRef.current = offscreen;
      setIsMattingActive(true);
    } catch (err) {
      console.error("抠图处理失败", err);
    } finally {
      setIsMattingProcessing(false);
    }
  }, [naturalSize, tolerance, smoothness]);

  // 当抠图激活且参数发生改变时重新计算
  useEffect(() => {
    if (isMattingActive && !showOriginal) {
      const timer = setTimeout(() => {
        performMatting();
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [tolerance, smoothness, performMatting, isMattingActive, showOriginal]);

  // 渲染最终输出并绘制到主预览 Canvas
  useEffect(() => {
    if (!imageLoaded || !previewCanvasRef.current || !naturalSize) return;

    const canvas = previewCanvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const src = isMattingActive && !showOriginal && mattedCanvasRef.current
      ? mattedCanvasRef.current
      : sourceImageRef.current;

    if (!src) return;

    const { width: tW, height: tH } = transformedSize;
    canvas.width = tW;
    canvas.height = tH;

    ctx.save();
    ctx.clearRect(0, 0, tW, tH);

    // 平移到中心进行旋转和翻转
    ctx.translate(tW / 2, tH / 2);
    ctx.rotate((rotation * Math.PI) / 180);
    ctx.scale(flipH ? -1 : 1, flipV ? -1 : 1);

    const origW = naturalSize.width;
    const origH = naturalSize.height;
    ctx.drawImage(src, -origW / 2, -origH / 2, origW, origH);
    ctx.restore();
  }, [imageLoaded, naturalSize, transformedSize, rotation, flipH, flipV, isMattingActive, showOriginal]);

  // 裁剪手柄拖拽交互处理
  const dragRef = useRef<{
    handle: string;
    startX: number;
    startY: number;
    initialCrop: CropRect;
  } | null>(null);

  const startDrag = (handle: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = {
      handle,
      startX: e.clientX,
      startY: e.clientY,
      initialCrop: { ...crop },
    };

    const onMouseMove = (moveEv: MouseEvent) => {
      if (!dragRef.current || !containerRef.current) return;
      const { handle: curHandle, startX, startY, initialCrop } = dragRef.current;
      const rect = containerRef.current.getBoundingClientRect();
      const deltaX = ((moveEv.clientX - startX) / rect.width) * 100;
      const deltaY = ((moveEv.clientY - startY) / rect.height) * 100;

      const targetRatio = PRESET_RATIOS[aspectPreset];

      if (curHandle === "move") {
        // 整体平移裁剪框
        let nextX = initialCrop.x + deltaX;
        let nextY = initialCrop.y + deltaY;
        nextX = Math.max(0, Math.min(100 - initialCrop.width, nextX));
        nextY = Math.max(0, Math.min(100 - initialCrop.height, nextY));
        setCrop((prev) => ({ ...prev, x: nextX, y: nextY }));
      } else {
        // 调节尺寸
        let newX = initialCrop.x;
        let newY = initialCrop.y;
        let newW = initialCrop.width;
        let newH = initialCrop.height;

        if (curHandle.includes("e")) newW = Math.max(5, Math.min(100 - initialCrop.x, initialCrop.width + deltaX));
        if (curHandle.includes("s")) newH = Math.max(5, Math.min(100 - initialCrop.y, initialCrop.height + deltaY));
        if (curHandle.includes("w")) {
          const maxDelta = initialCrop.width - 5;
          const actualDelta = Math.max(-initialCrop.x, Math.min(maxDelta, deltaX));
          newX = initialCrop.x + actualDelta;
          newW = initialCrop.width - actualDelta;
        }
        if (curHandle.includes("n")) {
          const maxDelta = initialCrop.height - 5;
          const actualDelta = Math.max(-initialCrop.y, Math.min(maxDelta, deltaY));
          newY = initialCrop.y + actualDelta;
          newH = initialCrop.height - actualDelta;
        }

        // 如果锁定了比例
        if (targetRatio) {
          const containerAspect = transformedSize.width / transformedSize.height;
          // 计算新比例对应的理论高度
          const desiredHeight = (newW * containerAspect) / targetRatio;
          if (newY + desiredHeight <= 100) {
            newH = desiredHeight;
          } else {
            newH = 100 - newY;
            newW = (newH * targetRatio) / containerAspect;
          }
        }

        setCrop({
          x: Math.max(0, Math.min(95, newX)),
          y: Math.max(0, Math.min(95, newY)),
          width: Math.max(5, Math.min(100 - newX, newW)),
          height: Math.max(5, Math.min(100 - newY, newH)),
        });
      }
    };

    const onMouseUp = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  };

  // 生成裁切并经过所有效果处理的高清图片 Canvas
  const generateExportCanvas = useCallback((): HTMLCanvasElement | null => {
    if (!naturalSize) return null;

    const { width: tW, height: tH } = transformedSize;
    const pxX = Math.round((crop.x / 100) * tW);
    const pxY = Math.round((crop.y / 100) * tH);
    const pxW = Math.max(1, Math.round((crop.width / 100) * tW));
    const pxH = Math.max(1, Math.round((crop.height / 100) * tH));

    const exportCanvas = document.createElement("canvas");
    exportCanvas.width = pxW;
    exportCanvas.height = pxH;
    const ctx = exportCanvas.getContext("2d");
    if (!ctx) return null;

    // 先创建带有变换的全图 Canvas
    const fullTransformedCanvas = document.createElement("canvas");
    fullTransformedCanvas.width = tW;
    fullTransformedCanvas.height = tH;
    const fullCtx = fullTransformedCanvas.getContext("2d");
    if (!fullCtx) return null;

    const src = isMattingActive && !showOriginal && mattedCanvasRef.current
      ? mattedCanvasRef.current
      : sourceImageRef.current;
    if (!src) return null;

    fullCtx.translate(tW / 2, tH / 2);
    fullCtx.rotate((rotation * Math.PI) / 180);
    fullCtx.scale(flipH ? -1 : 1, flipV ? -1 : 1);
    fullCtx.drawImage(src, -naturalSize.width / 2, -naturalSize.height / 2, naturalSize.width, naturalSize.height);

    // 裁切对应区域到 exportCanvas
    ctx.drawImage(fullTransformedCanvas, pxX, pxY, pxW, pxH, 0, 0, pxW, pxH);
    return exportCanvas;
  }, [naturalSize, transformedSize, crop, isMattingActive, showOriginal, rotation, flipH, flipV]);

  // 生成智能规范的输出文件名
  const getOutputFilename = useCallback((ext: string = "png"): string => {
    const cleanTitle = (title || "image")
      .replace(/\.[^.]+$/, "")
      .replace(/[^\w\u4e00-\u9fa5_-]/g, "_")
      .slice(0, 30);
    const tags: string[] = [];
    if (isMattingActive) tags.push("matting");
    if (aspectPreset !== "free") tags.push(aspectPreset.replace(":", "-"));
    if (rotation !== 0) tags.push(`r${rotation}`);
    if (flipH) tags.push("fliph");
    if (flipV) tags.push("flipv");
    const tagStr = tags.length ? `_${tags.join("_")}` : "_edited";
    return `${cleanTitle}${tagStr}.${ext}`;
  }, [title, isMattingActive, aspectPreset, rotation, flipH, flipV]);

  // 本地直接下载
  const handleDownload = useCallback(() => {
    try {
      const canvas = generateExportCanvas();
      if (!canvas) {
        setFeedback({ type: "error", text: "无法生成导出图片，请稍候重试" });
        return;
      }

      canvas.toBlob((blob) => {
        if (!blob) {
          setFeedback({ type: "error", text: "图片转为文件流失败" });
          return;
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const filename = getOutputFilename("png");
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        setIsDownloaded(true);
        setFeedback({ type: "success", text: `已下载到本地: ${filename}` });
        setTimeout(() => setIsDownloaded(false), 2500);
        setTimeout(() => setFeedback((f) => f?.type === "success" ? null : f), 3000);
      }, "image/png");
    } catch (err) {
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "下载失败，可能由于跨域安全限制",
      });
    }
  }, [generateExportCanvas, getOutputFilename]);

  // 转化为 File 对象并保存
  const createExportFile = useCallback(async (): Promise<{ file: File; width: number; height: number; aspectRatio: number } | null> => {
    const canvas = generateExportCanvas();
    if (!canvas) return null;

    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (!blob) {
          reject(new Error("生成图片文件流失败"));
          return;
        }
        const filename = getOutputFilename("png");
        const file = new File([blob], filename, { type: "image/png" });
        resolve({
          file,
          width: canvas.width,
          height: canvas.height,
          aspectRatio: canvas.width / canvas.height,
        });
      }, "image/png");
    });
  }, [generateExportCanvas, getOutputFilename]);

  // 操作 1：保存为项目新资产
  const handleSaveAsAsset = async () => {
    try {
      setSavingAction("asset");
      setFeedback(null);
      const result = await createExportFile();
      if (!result) return;
      await onSaveAsAsset(result.file, {
        width: result.width,
        height: result.height,
        aspectRatio: result.aspectRatio,
      });
      onOpenChange(false);
    } catch (err) {
      console.error("保存资产失败", err);
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "保存为新资产失败，请检查网络或后端状态",
      });
    } finally {
      setSavingAction(null);
    }
  };

  // 操作 2：更新当前节点图片
  const handleUpdateCurrentNode = async () => {
    if (!nodeId || !onUpdateNodeImage) return;
    try {
      setSavingAction("update-node");
      setFeedback(null);
      const result = await createExportFile();
      if (!result) return;
      const newAsset = await onSaveAsAsset(result.file, {
        width: result.width,
        height: result.height,
        aspectRatio: result.aspectRatio,
      });
      if (newAsset) {
        await onUpdateNodeImage(nodeId, newAsset, result.aspectRatio);
      }
      onOpenChange(false);
    } catch (err) {
      console.error("更新节点失败", err);
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "更新当前节点图片失败",
      });
    } finally {
      setSavingAction(null);
    }
  };

  // 操作 3：在画布新建衍生节点
  const handleCreateDerivedNode = async () => {
    if (!nodeId || !onCreateDerivedNode) return;
    try {
      setSavingAction("derived-node");
      setFeedback(null);
      const result = await createExportFile();
      if (!result) return;
      const newAsset = await onSaveAsAsset(result.file, {
        width: result.width,
        height: result.height,
        aspectRatio: result.aspectRatio,
      });
      if (newAsset) {
        await onCreateDerivedNode(nodeId, newAsset, result.aspectRatio);
      }
      onOpenChange(false);
    } catch (err) {
      console.error("创建衍生节点失败", err);
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "创建衍生图片节点失败",
      });
    } finally {
      setSavingAction(null);
    }
  };

  if (!open) return null;

  // 计算当前裁剪框像素尺寸
  const currentCropPixelWidth = Math.round((crop.width / 100) * transformedSize.width);
  const currentCropPixelHeight = Math.round((crop.height / 100) * transformedSize.height);

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-black/80 p-4 backdrop-blur-md animate-in fade-in duration-200"
      role="dialog"
      aria-modal="true"
      aria-label="图片编辑工作台"
    >
      <Card className="flex flex-col w-full max-w-6xl h-[90vh] border-white/10 bg-zinc-950/95 text-zinc-100 shadow-2xl shadow-black/80 overflow-hidden">
        {/* 顶部标题与控制 */}
        <header className="flex items-center justify-between border-b border-white/10 px-6 py-3.5 bg-zinc-900/60">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center size-8 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              <Crop className="size-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold tracking-tight flex items-center gap-2">
                图片编辑与预处理
                <Badge variant="outline" className="text-xs font-normal border-white/10 text-zinc-400">
                  {transformedSize.width} × {transformedSize.height}
                </Badge>
              </h2>
              <p className="text-xs text-zinc-400 truncate max-w-md">{title}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleReset}
              className="text-zinc-400 hover:text-zinc-100 text-xs"
              title="重置所有编辑"
            >
              <RotateCcw className="size-3.5 mr-1" />
              重置
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDownload}
              className={`border-white/10 text-xs transition-colors ${
                isDownloaded
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                  : "text-zinc-200 hover:text-white"
              }`}
            >
              {isDownloaded ? (
                <Check className="size-3.5 mr-1" />
              ) : (
                <Download className="size-3.5 mr-1" />
              )}
              {isDownloaded ? "已下载" : "下载图片"}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => onOpenChange(false)}
              className="text-zinc-400 hover:text-zinc-100"
              aria-label="关闭编辑器"
            >
              <X className="size-4" />
            </Button>
          </div>
        </header>

        {feedback && (
          <div
            className={`px-6 py-2 text-xs flex items-center justify-between border-b ${
              feedback.type === "success"
                ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
                : "bg-red-500/10 text-red-300 border-red-500/20"
            }`}
          >
            <span>{feedback.text}</span>
            <button
              type="button"
              onClick={() => setFeedback(null)}
              className="opacity-70 hover:opacity-100"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )}

        {/* 主编辑工作区 */}
        <div className="flex flex-1 min-h-0 divide-x divide-white/10">
          {/* 左侧/中间：图片交互裁剪区 */}
          <div className="flex-1 flex flex-col min-w-0 bg-zinc-950/70 p-6 select-none relative">
            {/* 画布主视口容器 */}
            <div
              ref={containerRef}
              className="flex-1 flex items-center justify-center relative overflow-hidden rounded-xl border border-white/10 bg-[#121214] shadow-inner"
              style={{
                backgroundImage: `
                  linear-gradient(45deg, #1c1c1f 25%, transparent 25%),
                  linear-gradient(-45deg, #1c1c1f 25%, transparent 25%),
                  linear-gradient(45deg, transparent 75%, #1c1c1f 75%),
                  linear-gradient(-45deg, transparent 75%, #1c1c1f 75%)
                `,
                backgroundSize: "20px 20px",
                backgroundPosition: "0 0, 0 10px, 10px -10px, -10px 0px",
              }}
            >
              {loadError ? (
                <div className="text-center p-6 text-red-400 text-sm max-w-sm">
                  <p>{loadError}</p>
                </div>
              ) : !imageLoaded ? (
                <div className="flex flex-col items-center gap-2 text-zinc-400">
                  <LoaderCircle className="size-6 animate-spin text-indigo-400" />
                  <span className="text-xs">加载高清素材中...</span>
                </div>
              ) : (
                <div
                  className="relative max-w-full max-h-full flex items-center justify-center"
                  style={{
                    aspectRatio: `${transformedSize.width} / ${transformedSize.height}`,
                  }}
                >
                  {/* 实际渲染的图像 Canvas */}
                  <canvas
                    ref={previewCanvasRef}
                    className="max-w-full max-h-[calc(90vh-210px)] object-contain rounded-md shadow-2xl block pointer-events-none"
                  />

                  {/* 裁剪遮罩与裁剪框层 */}
                  <div className="absolute inset-0 pointer-events-auto">
                    {/* 半透明暗色遮罩 */}
                    <div
                      className="absolute inset-0 bg-black/60 pointer-events-none"
                      style={{
                        clipPath: `polygon(
                          0% 0%, 100% 0%, 100% 100%, 0% 100%,
                          0% ${crop.y}%,
                          ${crop.x}% ${crop.y}%,
                          ${crop.x}% ${crop.y + crop.height}%,
                          ${crop.x + crop.width}% ${crop.y + crop.height}%,
                          ${crop.x + crop.width}% ${crop.y}%,
                          0% ${crop.y}%
                        )`,
                      }}
                    />

                    {/* 可拖拽交互裁剪框 */}
                    <div
                      className="absolute border-2 border-indigo-400 shadow-[0_0_0_1px_rgba(0,0,0,0.5)] cursor-move group"
                      style={{
                        left: `${crop.x}%`,
                        top: `${crop.y}%`,
                        width: `${crop.width}%`,
                        height: `${crop.height}%`,
                      }}
                      onMouseDown={(e) => startDrag("move", e)}
                    >
                      {/* 三分构图九宫格网格线 */}
                      <div className="absolute inset-0 grid grid-cols-3 grid-rows-3 pointer-events-none opacity-40 group-hover:opacity-80 transition-opacity">
                        <div className="border-r border-b border-white/60" />
                        <div className="border-r border-b border-white/60" />
                        <div className="border-b border-white/60" />
                        <div className="border-r border-b border-white/60" />
                        <div className="border-r border-b border-white/60" />
                        <div className="border-b border-white/60" />
                        <div className="border-r border-white/60" />
                        <div className="border-r border-white/60" />
                        <div />
                      </div>

                      {/* 四个角的缩放手柄 */}
                      <div
                        className="absolute -top-2 -left-2 size-4 bg-white border-2 border-indigo-600 rounded-sm cursor-nw-resize shadow-md"
                        onMouseDown={(e) => startDrag("nw", e)}
                      />
                      <div
                        className="absolute -top-2 -right-2 size-4 bg-white border-2 border-indigo-600 rounded-sm cursor-ne-resize shadow-md"
                        onMouseDown={(e) => startDrag("ne", e)}
                      />
                      <div
                        className="absolute -bottom-2 -left-2 size-4 bg-white border-2 border-indigo-600 rounded-sm cursor-sw-resize shadow-md"
                        onMouseDown={(e) => startDrag("sw", e)}
                      />
                      <div
                        className="absolute -bottom-2 -right-2 size-4 bg-white border-2 border-indigo-600 rounded-sm cursor-se-resize shadow-md"
                        onMouseDown={(e) => startDrag("se", e)}
                      />

                      {/* 四条边的缩放手柄 */}
                      <div
                        className="absolute -top-1.5 left-1/2 -translate-x-1/2 w-6 h-3 bg-white/90 border border-indigo-600 rounded-sm cursor-n-resize shadow-md"
                        onMouseDown={(e) => startDrag("n", e)}
                      />
                      <div
                        className="absolute -bottom-1.5 left-1/2 -translate-x-1/2 w-6 h-3 bg-white/90 border border-indigo-600 rounded-sm cursor-s-resize shadow-md"
                        onMouseDown={(e) => startDrag("s", e)}
                      />
                      <div
                        className="absolute top-1/2 -left-1.5 -translate-y-1/2 w-3 h-6 bg-white/90 border border-indigo-600 rounded-sm cursor-w-resize shadow-md"
                        onMouseDown={(e) => startDrag("w", e)}
                      />
                      <div
                        className="absolute top-1/2 -right-1.5 -translate-y-1/2 w-3 h-6 bg-white/90 border border-indigo-600 rounded-sm cursor-e-resize shadow-md"
                        onMouseDown={(e) => startDrag("e", e)}
                      />

                      {/* 实时尺寸提示胶囊 */}
                      <div className="absolute bottom-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full bg-black/80 backdrop-blur-md text-[10px] font-medium text-white/90 border border-white/10 pointer-events-none select-none">
                        {currentCropPixelWidth} × {currentCropPixelHeight}
                        {aspectPreset !== "free" && ` (${aspectPreset})`}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* 画布底部工具快捷栏 */}
            <div className="mt-4 flex items-center justify-between text-xs text-zinc-400">
              <div className="flex items-center gap-2">
                <span>旋转与翻转：</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setRotation((r) => (r + 90) % 360)}
                  className="border-white/10 h-7 px-2.5 text-xs text-zinc-300"
                  title="顺时针旋转90°"
                >
                  <RotateCw className="size-3.5 mr-1" />
                  90°
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setFlipH((f) => !f)}
                  className={`border-white/10 h-7 px-2.5 text-xs ${flipH ? "bg-indigo-500/20 text-indigo-300 border-indigo-500/40" : "text-zinc-300"}`}
                  title="水平镜像翻转"
                >
                  <FlipHorizontal className="size-3.5 mr-1" />
                  水平翻转
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setFlipV((f) => !f)}
                  className={`border-white/10 h-7 px-2.5 text-xs ${flipV ? "bg-indigo-500/20 text-indigo-300 border-indigo-500/40" : "text-zinc-300"}`}
                  title="垂直翻转"
                >
                  <FlipVertical className="size-3.5 mr-1" />
                  垂直翻转
                </Button>
              </div>

              {isMattingActive && (
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="border-white/10 h-7 px-2.5 text-xs text-zinc-300"
                    onMouseDown={() => setShowOriginal(true)}
                    onMouseUp={() => setShowOriginal(false)}
                    onTouchStart={() => setShowOriginal(true)}
                    onTouchEnd={() => setShowOriginal(false)}
                  >
                    {showOriginal ? <EyeOff className="size-3.5 mr-1" /> : <Eye className="size-3.5 mr-1" />}
                    按住对比原图
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* 右侧：功能控制面板 */}
          <aside className="w-80 flex flex-col bg-zinc-900/40 p-5 overflow-y-auto space-y-6">
            {/* 功能一：画幅比例选择 */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  画幅预设 (Aspect Ratio)
                </Label>
                <span className="text-[11px] text-zinc-500">
                  {PRESET_LABELS[aspectPreset].desc}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-1.5">
                {(Object.keys(PRESET_RATIOS) as AspectRatioPreset[]).map((preset) => {
                  const isActive = aspectPreset === preset;
                  return (
                    <Button
                      key={preset}
                      variant={isActive ? "default" : "outline"}
                      size="sm"
                      onClick={() => applyPresetRatio(preset)}
                      className={`h-8 text-xs font-medium justify-center border-white/10 ${
                        isActive
                          ? "bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm"
                          : "text-zinc-300 hover:text-zinc-100 hover:bg-white/[0.05]"
                      }`}
                    >
                      {PRESET_LABELS[preset].label}
                    </Button>
                  );
                })}
              </div>
            </div>

            <Separator className="bg-white/10" />

            {/* 功能二：一键智能抠图 */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                  <Sparkles className="size-3.5 text-amber-400" />
                  主体抠图 (Matting)
                </Label>
                {isMattingActive && (
                  <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px]">
                    已去除背景
                  </Badge>
                )}
              </div>

              <div className="p-3.5 rounded-xl border border-white/10 bg-white/[0.02] space-y-3">
                <p className="text-xs text-zinc-400 leading-relaxed">
                  基于智能色域与轮廓分析，一键消除纯色或摄影棚背景，自动生成透明背景 PNG。
                </p>

                <Button
                  variant={isMattingActive ? "secondary" : "default"}
                  size="sm"
                  disabled={isMattingProcessing}
                  onClick={() => {
                    if (isMattingActive) {
                      setIsMattingActive(false);
                    } else {
                      performMatting();
                    }
                  }}
                  className={`w-full h-9 text-xs font-medium justify-center transition-all ${
                    isMattingActive
                      ? "border border-white/20 text-zinc-300 hover:bg-white/10"
                      : "bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-zinc-950 font-semibold shadow-md shadow-orange-500/20"
                  }`}
                >
                  {isMattingProcessing ? (
                    <>
                      <LoaderCircle className="size-3.5 mr-1.5 animate-spin" />
                      正在提取主体...
                    </>
                  ) : isMattingActive ? (
                    <>
                      <RotateCcw className="size-3.5 mr-1.5" />
                      还原原图背景
                    </>
                  ) : (
                    <>
                      <Wand2 className="size-3.5 mr-1.5" />
                      一键去除背景
                    </>
                  )}
                </Button>

                {/* 抠图微调参数 */}
                {isMattingActive && (
                  <div className="pt-2 space-y-3 animate-in fade-in duration-150">
                    <div className="space-y-1.5">
                      <div className="flex justify-between text-[11px] text-zinc-400">
                        <span>容差阈值 (Sensitivity)</span>
                        <span className="font-mono text-zinc-300">{tolerance}</span>
                      </div>
                      <input
                        type="range"
                        min="10"
                        max="85"
                        value={tolerance}
                        onChange={(e) => setTolerance(Number(e.target.value))}
                        className="w-full accent-amber-400 h-1.5 bg-zinc-800 rounded-lg cursor-pointer"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <div className="flex justify-between text-[11px] text-zinc-400">
                        <span>边缘平滑 (Feather)</span>
                        <span className="font-mono text-zinc-300">{smoothness} px</span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="5"
                        value={smoothness}
                        onChange={(e) => setSmoothness(Number(e.target.value))}
                        className="w-full accent-amber-400 h-1.5 bg-zinc-800 rounded-lg cursor-pointer"
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="flex-1" />

            <Separator className="bg-white/10" />

            {/* 底部保存与联动动作 */}
            <div className="space-y-2 pt-2">
              <Button
                variant="default"
                size="sm"
                disabled={Boolean(savingAction)}
                onClick={handleSaveAsAsset}
                className="w-full h-9 bg-indigo-600 hover:bg-indigo-500 text-white font-medium shadow-md shadow-indigo-600/30"
              >
                {savingAction === "asset" ? (
                  <LoaderCircle className="size-4 animate-spin mr-1.5" />
                ) : (
                  <Check className="size-4 mr-1.5" />
                )}
                保存为新资产
              </Button>

              {nodeId && onUpdateNodeImage && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={Boolean(savingAction)}
                  onClick={handleUpdateCurrentNode}
                  className="w-full h-8 border-white/10 text-xs text-zinc-300 hover:text-white hover:bg-white/[0.05]"
                >
                  {savingAction === "update-node" ? (
                    <LoaderCircle className="size-3.5 animate-spin mr-1.5" />
                  ) : null}
                  更新当前节点图片
                </Button>
              )}

              {nodeId && onCreateDerivedNode && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={Boolean(savingAction)}
                  onClick={handleCreateDerivedNode}
                  className="w-full h-8 text-xs text-zinc-400 hover:text-zinc-200"
                >
                  {savingAction === "derived-node" ? (
                    <LoaderCircle className="size-3.5 animate-spin mr-1.5" />
                  ) : (
                    <Plus className="size-3.5 mr-1" />
                  )}
                  在右侧新建图片节点
                </Button>
              )}
            </div>
          </aside>
        </div>
      </Card>
    </div>
  );
}
