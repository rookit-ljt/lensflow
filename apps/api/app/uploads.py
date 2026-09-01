import base64
import uuid
from pathlib import Path

from .config import Settings

IMAGE_TYPES_BY_SUFFIX = {
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
SUFFIX_BY_IMAGE_TYPE = {media_type: suffix for suffix, media_type in IMAGE_TYPES_BY_SUFFIX.items()}


def detect_image_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def store_uploaded_image(
    settings: Settings,
    upload_id: uuid.UUID,
    content: bytes,
    media_type: str,
) -> Path:
    suffix = SUFFIX_BY_IMAGE_TYPE[media_type]
    directory = Path(settings.upload_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{upload_id}{suffix}"
    target.write_bytes(content)
    return target


def find_uploaded_image(settings: Settings, upload_id: uuid.UUID) -> tuple[Path, str] | None:
    directory = Path(settings.upload_directory).expanduser().resolve()
    for suffix, media_type in IMAGE_TYPES_BY_SUFFIX.items():
        candidate = directory / f"{upload_id}{suffix}"
        if candidate.is_file():
            return candidate, media_type
    return None


def uploaded_image_data_url(settings: Settings, upload_id: uuid.UUID) -> str | None:
    located = find_uploaded_image(settings, upload_id)
    if located is None:
        return None
    path, media_type = located
    content = path.read_bytes()
    if not content or len(content) > settings.upload_max_bytes:
        return None
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{media_type};base64,{encoded}"
