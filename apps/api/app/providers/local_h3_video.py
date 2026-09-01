import base64
import binascii
import re
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from ..config import Settings
from .base import (
    GenerationRequest,
    GenerationResult,
    prompt_with_text_context,
)


class LocalH3VideoProvider:
    """Submits and polls the local asynchronous MiniMax H3 HTTP service."""

    name = "local_h3"

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.client = client
        self.sleep = sleep

    def generate(self, request: GenerationRequest) -> GenerationResult:
        base_url = self.settings.local_video_base_url.strip().rstrip("/")
        if not base_url:
            raise RuntimeError("未配置 LOCAL_VIDEO_BASE_URL，无法调用本地 H3 视频模型")

        parameters = request.parameters or {}
        reference_mode = self._reference_mode(parameters)
        prompt = request.prompt if reference_mode == "ref2va" else prompt_with_text_context(request)
        if reference_mode == "ref2va":
            self._validate_ref2va_prompt(prompt)
        camera_motion = parameters.get("camera_motion")
        if (
            reference_mode != "ref2va"
            and isinstance(camera_motion, str)
            and camera_motion.strip() not in {"", "自动"}
        ):
            prompt = f"{prompt}，镜头运动：{camera_motion.strip()}"

        payload: dict[str, Any] = {
            "prompt": prompt,
            "preset": self._preset(parameters),
            "seconds": self._seconds(parameters.get("duration_seconds"), request.duration_seconds),
            "steps": self._bounded_int(parameters.get("steps"), default=4, minimum=1, maximum=50),
            "output_name": self._output_name(parameters.get("output_name"), request.generation_id),
        }
        if payload["preset"] == "custom":
            payload["width"] = self._dimension(parameters.get("width"), 256)
            payload["height"] = self._dimension(parameters.get("height"), 256)
        seed = parameters.get("seed")
        if isinstance(seed, int) and seed >= 0:
            payload["seed"] = seed

        if self.client is not None:
            return self._generate_with_client(self.client, base_url, payload, request)
        timeout = httpx.Timeout(self.settings.local_video_request_timeout_seconds, connect=10)
        with httpx.Client(timeout=timeout) as client:
            return self._generate_with_client(client, base_url, payload, request)

    def _generate_with_client(
        self,
        client: httpx.Client,
        base_url: str,
        payload: dict[str, Any],
        request: GenerationRequest,
    ) -> GenerationResult:
        with TemporaryDirectory(prefix=f"libtv-h3-{request.generation_id[:8]}-") as temp_dir:
            payload.update(self._reference_payload(client, request, Path(temp_dir)))
            return self._submit_and_poll(client, base_url, payload, request)

    def _reference_payload(
        self,
        client: httpx.Client,
        request: GenerationRequest,
        temp_dir: Path,
    ) -> dict[str, Any]:
        parameters = request.parameters or {}
        reference_mode = self._reference_mode(parameters)
        image_contexts = [
            context
            for context in request.contexts
            if context.kind == "image" and context.image_url
        ]
        if reference_mode == "text":
            return {}

        contexts_by_id = {context.node_id: context for context in image_contexts}
        if reference_mode == "ref2va":
            if parameters.get("first_frame_node_id") or parameters.get("last_frame_node_id"):
                raise RuntimeError("H3 全参考模式不能同时使用首帧或尾帧")
            raw_reference_ids = parameters.get("reference_image_node_ids")
            if not isinstance(raw_reference_ids, list):
                raise RuntimeError("H3 全参考模式缺少有序参考图片")
            reference_ids = [item for item in raw_reference_ids if isinstance(item, str) and item]
            if not reference_ids:
                raise RuntimeError("H3 全参考模式至少需要 1 张参考图片")
            if len(reference_ids) > 12:
                raise RuntimeError("H3 全参考模式最多支持 12 张参考图片")
            if len(reference_ids) != len(set(reference_ids)):
                raise RuntimeError("H3 全参考模式不能重复引用同一张图片")

            references: list[str] = []
            for index, node_id in enumerate(reference_ids, start=1):
                context = contexts_by_id.get(node_id)
                if context is None or not context.image_url:
                    raise RuntimeError(f"第 {index} 张全参考图片已不在当前视频节点的素材中")
                references.append(self._materialize_frame(
                    client,
                    context.image_url,
                    temp_dir,
                    f"reference_{index:02d}",
                ))
            return {"reference_images": references}

        if reference_mode != "keyframe":
            raise RuntimeError(f"不支持的视频参考模式：{reference_mode}")
        first_id = parameters.get("first_frame_node_id")
        last_id = parameters.get("last_frame_node_id")

        frame_payload: dict[str, str] = {}
        for field, node_id in (("first_frame", first_id), ("last_frame", last_id)):
            if not isinstance(node_id, str) or not node_id:
                continue
            context = contexts_by_id.get(node_id)
            if context is None or not context.image_url:
                raise RuntimeError(f"所选{self._frame_label(field)}已不在当前视频节点的图片连线中")
            frame_payload[field] = self._materialize_frame(
                client,
                context.image_url,
                temp_dir,
                field,
            )
        return frame_payload

    def _materialize_frame(
        self,
        client: httpx.Client,
        source: str,
        temp_dir: Path,
        field: str,
    ) -> str:
        data_match = re.fullmatch(r"data:(image/[\w.+-]+);base64,(.+)", source, re.DOTALL)
        if data_match:
            try:
                content = base64.b64decode(data_match.group(2), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError(f"{self._frame_label(field)}的 Base64 图片数据已损坏") from exc
            return self._write_frame(temp_dir, field, content, data_match.group(1))

        if source.startswith("file://"):
            source = unquote(urlparse(source).path)
        local_path = Path(source).expanduser()
        if local_path.is_absolute():
            if not local_path.is_file():
                raise RuntimeError(f"{self._frame_label(field)}文件不存在：{local_path}")
            return str(local_path.resolve())

        if source.startswith(("http://", "https://")):
            response = client.get(source)
            self._raise_for_status(response, f"{self._frame_label(field)}下载失败")
            if len(response.content) > 25 * 1024 * 1024:
                raise RuntimeError(f"{self._frame_label(field)}超过 25MB 限制")
            content_type = response.headers.get("content-type", "image/png").split(";", 1)[0]
            return self._write_frame(temp_dir, field, response.content, content_type)

        raise RuntimeError(f"{self._frame_label(field)}图片地址格式不受支持")

    @staticmethod
    def _write_frame(temp_dir: Path, field: str, content: bytes, content_type: str) -> str:
        if not content:
            raise RuntimeError("参考图片内容为空")
        suffix = {
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }.get(content_type.lower(), ".png")
        target = temp_dir / f"{field}{suffix}"
        target.write_bytes(content)
        return str(target)

    @staticmethod
    def _frame_label(field: str) -> str:
        if field.startswith("reference_"):
            try:
                return f"参考图 {int(field.removeprefix('reference_'))}"
            except ValueError:
                return "参考图"
        return "首帧" if field == "first_frame" else "尾帧"

    @staticmethod
    def _reference_mode(parameters: dict[str, Any]) -> str:
        value = parameters.get("video_reference_mode")
        if value in {"text", "keyframe", "ref2va"}:
            return str(value)
        if parameters.get("reference_image_node_ids"):
            return "ref2va"
        if parameters.get("first_frame_node_id") or parameters.get("last_frame_node_id"):
            return "keyframe"
        return "text"

    @staticmethod
    def _validate_ref2va_prompt(prompt: str) -> None:
        headings = (
            "subject_definitions:",
            "summary:",
            "retention_analysis:",
            "detailed_description:",
            "overall_soundscape:",
            "non_diegetic_music:",
        )
        positions = [prompt.find(heading) for heading in headings]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            raise RuntimeError("H3 全参考 Prompt 缺少规定的六段结构，请在视频节点中重新编译")

    def _submit_and_poll(
        self,
        client: httpx.Client,
        base_url: str,
        payload: dict[str, Any],
        request: GenerationRequest,
    ) -> GenerationResult:
        response = client.post(f"{base_url}/v1/generations", json=payload)
        self._raise_for_status(response, "本地 H3 视频任务创建失败")
        body = response.json()
        job_id = body.get("id")
        status_url = body.get("status_url")
        if not isinstance(job_id, str) or not job_id:
            raise RuntimeError("本地 H3 视频接口没有返回任务 ID")
        if not isinstance(status_url, str) or not status_url:
            status_url = f"/v1/jobs/{job_id}"

        deadline = time.monotonic() + self.settings.local_video_request_timeout_seconds
        status_endpoint = urljoin(f"{base_url}/", status_url.lstrip("/"))
        while time.monotonic() < deadline:
            status_response = client.get(status_endpoint)
            self._raise_for_status(status_response, "本地 H3 视频任务查询失败")
            job = status_response.json()
            status = str(job.get("status", "")).lower()
            if status == "succeeded":
                video_url = job.get("video_url") or f"/v1/jobs/{job_id}/video"
                if not isinstance(video_url, str) or not video_url:
                    raise RuntimeError("本地 H3 视频任务没有返回视频地址")
                return GenerationResult(
                    provider_job_id=job_id,
                    output_url=urljoin(f"{base_url}/", video_url.lstrip("/")),
                )
            if status in {"failed", "canceled", "cancelled", "interrupted"}:
                detail = job.get("error") or status
                raise RuntimeError(f"本地 H3 视频生成失败：{detail}")
            self.sleep(self.settings.local_video_poll_interval_seconds)
        raise RuntimeError("本地 H3 视频生成超时，请检查 8787 服务任务状态")

    @staticmethod
    def _preset(parameters: dict[str, Any]) -> str:
        value = str(parameters.get("preset") or "custom").lower()
        return value if value in {"preview", "720p", "custom"} else "custom"

    @staticmethod
    def _seconds(value: object, fallback: int) -> float:
        number = float(value) if isinstance(value, (int, float)) else float(fallback)
        return min(max(number, 0.2), 15.0)

    @staticmethod
    def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
        number = value if isinstance(value, int) else default
        return min(max(number, minimum), maximum)

    @staticmethod
    def _dimension(value: object, default: int) -> int:
        number = value if isinstance(value, int) else default
        number = min(max(number, 64), 2048)
        return max(64, number - number % 32)

    @staticmethod
    def _output_name(value: object, generation_id: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
        return f"libtv-{generation_id[:12]}"

    @staticmethod
    def _raise_for_status(response: httpx.Response, message: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                body = response.json()
                detail = body.get("message") or body.get("error") or response.text
            except ValueError:
                detail = response.text or "未知错误"
            raise RuntimeError(f"{message}（{response.status_code}）：{detail}") from exc
