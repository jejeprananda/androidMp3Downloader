import asyncio
import json
import re
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.models.schemas import SearchResultItem

YOUTUBE_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]{11}",
    re.IGNORECASE,
)


class YtdlpError(Exception):
    pass


def is_valid_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_URL_PATTERN.match(url.strip()))


def _extract_video_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if "youtu.be" in parsed.netloc:
        path = parsed.path.lstrip("/")
        return path[:11] if len(path) >= 11 else None

    if "youtube.com" in parsed.netloc:
        query = parse_qs(parsed.query)
        video_id = query.get("v", [None])[0]
        return video_id[:11] if video_id else None

    return None


async def _run_subprocess(cmd: list[str], timeout: int) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise YtdlpError("yt-dlp timed out")

    return process.returncode or 0, stdout, stderr


async def search_videos(query: str, limit: int, settings: Settings) -> list[SearchResultItem]:
    search_expr = f"ytsearch{limit}:{query}"
    cmd = [
        "yt-dlp",
        search_expr,
        "--flat-playlist",
        "-J",
        "--no-warnings",
        "--no-playlist",
    ]

    returncode, stdout, stderr = await _run_subprocess(cmd, timeout=120)
    if returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip() or "yt-dlp search failed"
        raise YtdlpError(message)

    try:
        data = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError:
        raise YtdlpError("Failed to parse yt-dlp search response")

    entries = data.get("entries") or []
    results: list[SearchResultItem] = []

    for entry in entries:
        video_id = entry.get("id")
        if not video_id:
            continue

        title = entry.get("title") or "Untitled"
        url = entry.get("url") or entry.get("webpage_url")
        if not url:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if url.startswith("http://") or url.startswith("https://"):
            video_url = url
        else:
            video_url = f"https://www.youtube.com/watch?v={video_id}"

        duration = entry.get("duration")
        thumbnail = entry.get("thumbnail")
        if not thumbnail and video_id:
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        results.append(
            SearchResultItem(
                id=video_id,
                title=title,
                url=video_url,
                duration=int(duration) if duration is not None else None,
                thumbnail=thumbnail,
            )
        )

    return results


async def get_video_title(url: str, settings: Settings) -> str:
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--print",
        "title",
        "--skip-download",
        url,
    ]

    returncode, stdout, stderr = await _run_subprocess(cmd, timeout=60)
    if returncode != 0:
        video_id = _extract_video_id(url)
        return f"video-{video_id or 'download'}"

    title = stdout.decode("utf-8", errors="replace").strip()
    return title or "download"


def _build_stream_command(url: str, format: str) -> list[str]:
    base = ["yt-dlp", "-o", "-", "--no-part", "--no-warnings", "--no-playlist"]

    if format == "mp3":
        return base + [
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            url,
        ]

    return base + [
        "-f",
        "best[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        url,
    ]


def sanitize_filename(title: str, extension: str) -> str:
    cleaned = re.sub(r"[^\w\s.-]", "", title, flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    if not cleaned:
        cleaned = "download"
    return f"{cleaned[:120]}.{extension}"


async def stream_media(url: str, format: str, settings: Settings) -> AsyncIterator[bytes]:
    cmd = _build_stream_command(url, format)
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        while True:
            try:
                chunk = await asyncio.wait_for(
                    process.stdout.read(65536),
                    timeout=settings.stream_timeout_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                raise YtdlpError("Stream timed out")

            if not chunk:
                break
            yield chunk

        stderr = await process.stderr.read()
        returncode = await process.wait()

        if returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip() or "yt-dlp stream failed"
            raise YtdlpError(message)
    except GeneratorExit:
        process.kill()
        await process.communicate()
        raise
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
