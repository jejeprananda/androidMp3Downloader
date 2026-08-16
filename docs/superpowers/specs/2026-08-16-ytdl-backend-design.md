# YT-DLP Backend API — Design Spec

**Date:** 2026-08-16  
**Status:** Approved  
**Scope:** Backend-only (Android app deferred)

## Overview

A Dockerized monolith API that searches YouTube videos and streams downloaded/converted media (MP3 or MP4) directly to clients without persisting files on the server. Intended as the backend for a future Android app.

## Goals

- Single-container deployment via Docker Compose for easy VPS deploy
- YouTube search without Google API key (yt-dlp `ytsearch`)
- Stream MP3/MP4 to client on demand (no server-side file storage)
- Private API protected by `X-API-Key` header

## Non-Goals (MVP)

- Android client
- YouTube Data API v3 integration
- Job queue / Redis / async job polling
- Playlist or batch downloads
- Database or download history
- Public unauthenticated access

## Architecture

**Pattern:** Monolith single container — API, yt-dlp, and ffmpeg in one image.

| Component | Choice |
|-----------|--------|
| Runtime | Python 3.12 |
| Framework | FastAPI |
| Download engine | yt-dlp (subprocess) |
| Conversion | ffmpeg (via yt-dlp post-processors) |
| Search | `ytsearch{N}:{query}` via yt-dlp JSON output |
| Auth | `X-API-Key` header on all routes except `/health` |
| Storage | None — stdout pipe streamed to HTTP response |

```
┌─────────────┐     HTTPS      ┌──────────────────────────────┐
│ Client App  │ ──────────────►│  Docker Container            │
│  (future)   │  X-API-Key     │  FastAPI                     │
└─────────────┘                │    ├─ /search  → yt-dlp JSON │
                               │    └─ /stream  → pipe stdout │
                               │         yt-dlp + ffmpeg      │
                               └──────────────────────────────┘
```

## Repository Structure

```
backend/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies/
│   │   └── auth.py           # X-API-Key validation
│   ├── routes/
│   │   ├── health.py
│   │   ├── search.py
│   │   └── stream.py
│   ├── services/
│   │   └── ytdlp.py          # search + stream subprocess
│   └── models/
│       └── schemas.py
docs/
└── superpowers/
    └── specs/
        └── 2026-08-16-ytdl-backend-design.md
```

## API Endpoints

### `GET /health`

- **Auth:** None
- **Purpose:** Docker health check and monitoring

**Response 200:**

```json
{ "status": "ok" }
```

### `GET /search`

- **Auth:** Required (`X-API-Key`)

**Query parameters:**

| Param | Type | Default | Constraints |
|-------|------|---------|-------------|
| `q` | string | — | Required, min 2 characters |
| `limit` | int | 10 | Max 25 |

**Response 200:**

```json
{
  "results": [
    {
      "id": "dQw4w9WgXcQ",
      "title": "Video title",
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "duration": 213,
      "thumbnail": "https://i.ytimg.com/vi/.../hqdefault.jpg"
    }
  ]
}
```

**Errors:**

| Status | Condition |
|--------|-----------|
| 400 | Missing/invalid query |
| 401 | Missing or invalid API key |
| 502 | yt-dlp search failure |

### `GET /stream`

- **Auth:** Required (`X-API-Key`)

**Query parameters:**

| Param | Type | Default | Constraints |
|-------|------|---------|-------------|
| `url` | string | — | Required, valid YouTube URL |
| `format` | string | `mp3` | `mp3` or `mp4` |

**Response 200:**

- `Content-Type`: `audio/mpeg` (mp3) or `video/mp4` (mp4)
- `Content-Disposition`: `attachment; filename="<sanitized-title>.mp3"`
- Body: chunked binary stream

**Errors:**

| Status | Condition |
|--------|-----------|
| 400 | Invalid URL or format |
| 401 | Missing or invalid API key |
| 429 | Concurrent stream limit exceeded |
| 502 | yt-dlp/ffmpeg failure (unavailable video, etc.) |

## Stream Flow

No files are written to disk. yt-dlp stdout is piped directly to the HTTP response.

```
Client: GET /stream?url=...&format=mp3
        │
        ▼
FastAPI StreamingResponse
        │
        ▼
subprocess: yt-dlp -o - --no-part ... URL
        │         (stdout pipe)
        ▼
Async chunk generator reads stdout → yields to client
        │
        ▼
Client receives bytes until complete or disconnect
```

**yt-dlp arguments:**

- **MP3:** `-o - --no-part -x --audio-format mp3 --audio-quality 0`
- **MP4:** `-o - --no-part -f "best[ext=mp4]/best" --merge-output-format mp4`

**Concurrency:**

- Environment variable `MAX_CONCURRENT_STREAMS` (default: 2)
- Additional requests receive 429 while limit is reached
- On client disconnect, kill the yt-dlp subprocess (no leftover files)

**Accepted trade-offs:**

- No server-side retry — client must re-request on failure
- HTTP connection must remain stable for entire download duration
- Long videos hold a connection open for minutes

## Configuration (Environment Variables)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | — | Secret for `X-API-Key` validation |
| `MAX_CONCURRENT_STREAMS` | No | 2 | Max simultaneous `/stream` requests |
| `STREAM_TIMEOUT_SECONDS` | No | 600 | Kill yt-dlp after this duration |
| `SEARCH_LIMIT_DEFAULT` | No | 10 | Default search result count |
| `SEARCH_LIMIT_MAX` | No | 25 | Maximum search result count |

## Security

- `API_KEY` stored in `.env`, never committed
- All routes except `/health` require matching `X-API-Key`
- Concurrent stream limit prevents resource exhaustion
- YouTube URLs validated before subprocess invocation
- Filename in `Content-Disposition` sanitized (no path traversal)

## Docker Deployment

**docker-compose.yml (concept):**

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

**Image contents:** `python:3.12-slim` + system `ffmpeg` + `yt-dlp` (pip) + FastAPI stack

No volume mount required — no persistent downloads directory.

**Production:** Reverse proxy (Nginx/Caddy) for HTTPS in front of port 8000.

## Error Handling

| Condition | Response |
|-----------|----------|
| Video unavailable / private | 502 with clear message |
| Non-YouTube URL | 400 |
| yt-dlp exceeds timeout | 502, process killed |
| Invalid API key | 401 |
| Concurrent limit hit | 429 |

**Logging:** Log request metadata (request ID, URL, format, stream duration, yt-dlp errors). Do not log API keys.

## Testing

**Local:**

```bash
docker compose up --build

curl http://localhost:8000/health

curl -H "X-API-Key: your-key" \
  "http://localhost:8000/search?q=lofi&limit=5"

curl -H "X-API-Key: your-key" \
  "http://localhost:8000/stream?url=https://www.youtube.com/watch?v=VIDEO_ID&format=mp3" \
  -o test.mp3
```

**Verify:**

- Health returns 200 without auth
- Search returns JSON with expected fields
- Stream produces valid MP3/MP4 file locally
- 401 without API key on protected routes
- 429 when concurrent limit exceeded

## Future Extensions (Post-MVP)

- Android client consuming this API
- YouTube Data API v3 for improved search (optional fallback)
- Async job model if streaming proves unreliable for mobile
- API key rotation / multiple keys
- Per-IP rate limiting
