import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.dependencies.auth import AuthContext, get_auth_context
from app.services.ytdlp import (
    YtdlpError,
    get_video_title,
    is_valid_youtube_url,
    sanitize_filename,
    stream_media,
)

router = APIRouter(tags=["stream"])

_stream_semaphore: asyncio.Semaphore | None = None


def _get_stream_semaphore(settings: Settings) -> asyncio.Semaphore:
    global _stream_semaphore
    if _stream_semaphore is None:
        _stream_semaphore = asyncio.Semaphore(settings.max_concurrent_streams)
    return _stream_semaphore


@router.get("/stream")
async def stream(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    url: Annotated[str, Query(min_length=10)],
    format: Annotated[str, Query(pattern="^(mp3|mp4)$")] = "mp3",
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> StreamingResponse:
    del auth  # auth enforced by dependency

    if format not in {"mp3", "mp4"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format must be mp3 or mp4")

    if not is_valid_youtube_url(url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid YouTube URL")

    semaphore = _get_stream_semaphore(settings)
    if semaphore.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent streams",
        )

    await semaphore.acquire()

    try:
        title = await get_video_title(url, settings)
    except YtdlpError:
        title = "download"

    media_type = "audio/mpeg" if format == "mp3" else "video/mp4"
    filename = sanitize_filename(title, format)

    async def media_generator():
        try:
            async for chunk in stream_media(url, format, settings):
                yield chunk
        finally:
            semaphore.release()

    return StreamingResponse(
        media_generator(),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )
