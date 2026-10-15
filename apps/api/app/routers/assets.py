from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..auth import CurrentUser
from ..config import get_settings
from ..db_models import Asset, StoredUpload
from ..deps import (
    DatabaseSession,
    asset_reference_count,
    get_owned_asset,
    get_owned_project,
    require_owned_upload,
)
from ..schemas import AssetRead, UploadRead
from ..uploads import detect_image_type, find_uploaded_image, store_uploaded_image

settings = get_settings()

router = APIRouter()


@router.post(
    "/api/uploads",
    response_model=UploadRead,
    status_code=status.HTTP_201_CREATED,
    tags=["uploads"],
)
async def upload_image(
    request: Request,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    session: DatabaseSession,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
) -> UploadRead:
    if project_id is not None:
        get_owned_project(session, user, project_id)
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="图片不能超过 10MB")
    buffer = bytearray()
    async for chunk in request.stream():
        if len(buffer) + len(chunk) > settings.upload_max_bytes:
            raise HTTPException(status_code=413, detail="图片不能超过 10MB")
        buffer.extend(chunk)
    content = bytes(buffer)
    if not content:
        raise HTTPException(status_code=422, detail="上传图片内容为空")
    media_type = detect_image_type(content)
    if media_type is None:
        raise HTTPException(status_code=415, detail="仅支持 PNG、JPG、WebP 和 GIF 图片")

    upload_id = uuid.uuid4()
    store_uploaded_image(settings, upload_id, content, media_type)
    upload = StoredUpload(
        id=upload_id,
        user_id=user.id,
        filename=filename,
        content_type=media_type,
        size=len(content),
    )
    session.add(upload)
    asset = Asset(
        user_id=user.id,
        project_id=project_id,
        source_upload_id=upload_id,
        kind="image",
        role="reference",
        filename=filename,
        content_type=media_type,
        size=len(content),
        url=str(request.url_for("read_upload", upload_id=upload_id)),
        metadata_json={"source": "upload"},
    )
    session.add(asset)
    session.commit()
    return UploadRead(
        id=upload_id,
        asset_id=asset.id,
        filename=filename,
        content_type=media_type,
        size=len(content),
        url=str(request.url_for("read_upload", upload_id=upload_id)),
    )


@router.get(
    "/api/assets",
    response_model=list[AssetRead],
    tags=["assets"],
)
def list_user_assets(
    session: DatabaseSession,
    user: CurrentUser,
    kind: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=120),
) -> list[Asset]:
    statement = (
        select(Asset)
        .where(Asset.user_id == user.id)
        .order_by(Asset.created_at.desc())
    )
    if kind:
        statement = statement.where(Asset.kind == kind)
    if q:
        statement = statement.where(Asset.filename.ilike(f"%{q}%"))
    return list(session.scalars(statement))


@router.get(
    "/api/projects/{project_id}/assets",
    response_model=list[AssetRead],
    tags=["assets"],
)
def list_project_assets(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
    kind: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=120),
) -> list[Asset]:
    get_owned_project(session, user, project_id)
    statement = (
        select(Asset)
        .where(Asset.project_id == project_id)
        .order_by(Asset.created_at.desc())
    )
    if kind:
        statement = statement.where(Asset.kind == kind)
    if q:
        statement = statement.where(Asset.filename.ilike(f"%{q}%"))
    return list(session.scalars(statement))


@router.get(
    "/api/assets/{asset_id}",
    response_model=AssetRead,
    tags=["assets"],
)
def get_asset(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Asset:
    return get_owned_asset(session, user, asset_id)


@router.delete(
    "/api/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["assets"],
)
def delete_asset(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Response:
    asset = get_owned_asset(session, user, asset_id)
    reference_count = asset_reference_count(session, asset)
    if reference_count:
        raise HTTPException(
            status_code=409,
            detail=f"资产仍被 {reference_count} 个画布节点引用，请先从节点移除",
        )

    source_upload = asset.source_upload
    upload_path = None
    if source_upload is not None:
        located = find_uploaded_image(settings, source_upload.id)
        upload_path = located[0] if located is not None else None

    session.delete(asset)
    if source_upload is not None:
        session.delete(source_upload)
    session.commit()
    if upload_path is not None:
        upload_path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/uploads/{upload_id}", name="read_upload", tags=["uploads"])
def read_upload(
    upload_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> FileResponse:
    require_owned_upload(session, user, upload_id)
    located = find_uploaded_image(settings, upload_id)
    if located is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    path, media_type = located
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
