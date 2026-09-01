import base64
import binascii
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import httpx

MAX_VIDEO_BYTES = 512 * 1024 * 1024


def extract_last_video_frame(source_url: str) -> bytes:
    """Download a generated video and return its final decodable frame as PNG."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("服务器未安装 FFmpeg，无法截取视频末帧")

    with TemporaryDirectory(prefix="libtv-last-frame-") as temp_dir:
        video_path = Path(temp_dir) / "source-video"
        frame_path = Path(temp_dir) / "last-frame.png"
        _materialize_video(source_url, video_path)
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-sseof",
            "-0.1",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-y",
            str(frame_path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("视频末帧截取超时") from exc
        if result.returncode != 0 or not frame_path.is_file():
            detail = result.stderr.decode("utf-8", errors="replace").strip()[-600:]
            raise RuntimeError(f"视频末帧截取失败：{detail or 'FFmpeg 未生成图片'}")
        content = frame_path.read_bytes()
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("FFmpeg 返回的末帧图片格式无效")
        return content


def _materialize_video(source_url: str, target: Path) -> None:
    if source_url.startswith("data:"):
        header, separator, payload = source_url.partition(",")
        if not separator or ";base64" not in header or not header.startswith("data:video/"):
            raise RuntimeError("视频数据格式无效")
        try:
            content = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("视频 Base64 数据已损坏") from exc
        if not content or len(content) > MAX_VIDEO_BYTES:
            raise RuntimeError("视频内容为空或超过 512MB 限制")
        target.write_bytes(content)
        return

    if urlsplit(source_url).scheme not in {"http", "https"}:
        raise RuntimeError("视频地址格式不受支持")
    try:
        with httpx.stream("GET", source_url, timeout=httpx.Timeout(300, connect=10)) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_VIDEO_BYTES:
                raise RuntimeError("视频超过 512MB 限制")
            total = 0
            with target.open("wb") as output:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_VIDEO_BYTES:
                        raise RuntimeError("视频超过 512MB 限制")
                    output.write(chunk)
    except httpx.HTTPError as exc:
        raise RuntimeError("无法读取视频文件，请确认生成服务仍在运行") from exc
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("视频内容为空")
