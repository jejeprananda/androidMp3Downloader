# YT-DLP Backend API — Design Spec

**Date:** 2026-08-16  
**Status:** Approved (updated: Google SSO)  
**Scope:** Backend-only (Android app deferred)

## Overview

A Dockerized monolith API that searches YouTube videos and streams downloaded/converted media (MP3 or MP4) directly to clients without persisting files on the server. Intended as the backend for a future Android app.

## Goals

- Single-container deployment via Docker Compose for easy VPS deploy
- YouTube search without Google API key (yt-dlp `ytsearch`)
- Stream MP3/MP4 to client on demand (no server-side file storage)
- Private API protected by **Google SSO** (JWT) and **API key** (dual auth)
- Google Sign-In optimized for future Android client (`id_token` exchange)

## Non-Goals (MVP)

- Android client implementation
- YouTube Data API v3 integration
- Job queue / Redis / async job polling
- Playlist or batch downloads
- Database or persistent user/download history
- Role-based access control beyond optional email allowlist

## Architecture

**Pattern:** Monolith single container — API, yt-dlp, and ffmpeg in one image.

| Component | Choice |
|-----------|--------|
| Runtime | Python 3.12 |
| Framework | FastAPI |
| Download engine | yt-dlp (subprocess) |
| Conversion | ffmpeg (via yt-dlp post-processors) |
| Search | `ytsearch{N}:{query}` via yt-dlp JSON output |
| User auth | Google SSO → server-issued JWT (`Authorization: Bearer`) |
| Service auth | `X-API-Key` header (scripts, local dev, service clients) |
| Token crypto | HS256 JWT signed with `JWT_SECRET` |
| Google verify | `google-auth` library (ID token + OAuth code flow) |
| Storage | None — stdout pipe streamed to HTTP response; no user DB |

```
┌─────────────┐   Bearer JWT /    ┌────────────────────────────────────┐
│ Android App │   X-API-Key       │  Docker Container                  │
│  (future)   │ ────────────────► │  FastAPI                           │
└─────────────┘                   │    ├─ /auth/google*  → Google SSO │
       │                          │    ├─ /search       → yt-dlp JSON  │
       │ Google Sign-In           │    └─ /stream       → pipe stdout│
       ▼                          │         yt-dlp + ffmpeg           │
  id_token ──POST /auth/google──► │                                    │
                                  └────────────────────────────────────┘
```

## Authentication Design

### Dual auth (both accepted on protected routes)

Protected routes (`/search`, `/stream`, `/auth/me`) accept **either**:

1. **`Authorization: Bearer <jwt>`** — JWT issued by this API after successful Google SSO
2. **`X-API-Key: <key>`** — static key from env (dev, curl, automation)

If both are present, Bearer JWT is preferred. Missing or invalid credentials → `401`.

### Google SSO flows

#### Flow A — Android / mobile (primary)

Designed for future Android app using Google Sign-In SDK:

1. Client obtains Google `id_token` via Google Sign-In
2. Client sends `POST /auth/google` with `{ "id_token": "..." }`
3. Server verifies `id_token` with Google (`GOOGLE_CLIENT_ID`)
4. Optional: reject if email not in `ALLOWED_EMAILS` allowlist
5. Server issues JWT (`access_token`) with expiry

No server-side session store — stateless JWT only.

#### Flow B — Web OAuth redirect (optional, same MVP)

For browser-based login or testing without mobile SDK:

1. `GET /auth/google/login` → redirect to Google consent screen
2. Google redirects to `GET /auth/google/callback?code=...`
3. Server exchanges code for tokens, verifies, issues JWT
4. Response: JSON with `access_token` (MVP) — no cookie/session cookie in v1

Redirect URIs must be registered in Google Cloud Console.

### JWT payload

```json
{
  "sub": "google-user-id",
  "email": "user@example.com",
  "name": "Display Name",
  "picture": "https://...",
  "iat": 1710000000,
  "exp": 1710003600
}
```

### Access control

- Default: any Google account with valid verified email
- If `ALLOWED_EMAILS` is set (comma-separated): only listed emails may obtain JWT
- `X-API-Key` bypasses email allowlist (intended for operators only)

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
│   │   └── auth.py           # JWT + X-API-Key validation
│   ├── routes/
│   │   ├── health.py
│   │   ├── auth.py           # Google SSO endpoints
│   │   ├── search.py
│   │   └── stream.py
│   ├── services/
│   │   ├── ytdlp.py          # search + stream subprocess
│   │   └── google_auth.py    # verify id_token, OAuth exchange
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

### `POST /auth/google`

- **Auth:** None
- **Purpose:** Exchange Google `id_token` (from mobile Sign-In) for API JWT

**Request body:**

```json
{
  "id_token": "eyJhbGciOiJSUzI1NiIs..."
}
```

**Response 200:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "sub": "google-user-id",
    "email": "user@example.com",
    "name": "Display Name",
    "picture": "https://lh3.googleusercontent.com/..."
  }
}
```

**Errors:**

| Status | Condition |
|--------|-----------|
| 400 | Missing `id_token` |
| 401 | Invalid or expired Google token |
| 403 | Email not in `ALLOWED_EMAILS` |

### `GET /auth/google/login`

- **Auth:** None
- **Purpose:** Start web OAuth flow — redirects to Google

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `redirect_uri` | string | — | Optional; must match Google Console allowlist |

### `GET /auth/google/callback`

- **Auth:** None
- **Purpose:** OAuth callback — exchange `code` for JWT

**Query parameters:** `code`, `state` (from Google)

**Response 200:** Same shape as `POST /auth/google` success response.

### `GET /auth/me`

- **Auth:** Required (Bearer JWT or `X-API-Key`)

**Response 200 (JWT user):**

```json
{
  "auth_type": "jwt",
  "user": {
    "sub": "google-user-id",
    "email": "user@example.com",
    "name": "Display Name",
    "picture": "https://..."
  }
}
```

**Response 200 (API key):**

```json
{
  "auth_type": "api_key",
  "user": null
}
```

### `GET /search`

- **Auth:** Required (Bearer JWT or `X-API-Key`)

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
| 401 | Missing or invalid credentials |
| 403 | JWT user not on allowlist (should not occur after login) |
| 502 | yt-dlp search failure |

### `GET /stream`

- **Auth:** Required (Bearer JWT or `X-API-Key`)

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
| 401 | Missing or invalid credentials |
| 429 | Concurrent stream limit exceeded |
| 502 | yt-dlp/ffmpeg failure (unavailable video, etc.) |

## Stream Flow

No files are written to disk. yt-dlp stdout is piped directly to the HTTP response.

```
Client: GET /stream?url=...&format=mp3
        Authorization: Bearer <jwt>
        │
        ▼
Auth dependency (JWT or API key)
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
| `GOOGLE_CLIENT_ID` | Yes | — | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Yes* | — | Required for web OAuth callback flow |
| `GOOGLE_REDIRECT_URI` | Yes* | — | e.g. `https://api.example.com/auth/google/callback` |
| `JWT_SECRET` | Yes | — | Secret for signing API JWTs |
| `JWT_EXPIRE_MINUTES` | No | 60 | JWT lifetime |
| `ALLOWED_EMAILS` | No | — | Comma-separated allowlist; empty = all Google users |
| `MAX_CONCURRENT_STREAMS` | No | 2 | Max simultaneous `/stream` requests |
| `STREAM_TIMEOUT_SECONDS` | No | 600 | Kill yt-dlp after this duration |
| `SEARCH_LIMIT_DEFAULT` | No | 10 | Default search result count |
| `SEARCH_LIMIT_MAX` | No | 25 | Maximum search result count |

\* Required if web OAuth flow (`/auth/google/login`) is enabled.

## Google Cloud Setup

1. Create project in [Google Cloud Console](https://console.cloud.google.com/)
2. Configure **OAuth 2.0 Client ID**:
   - Type **Android** (for future app) — package name + SHA-1
   - Type **Web application** — for `/auth/google/callback` redirect URI
3. Enable Google Identity / People API if required by console
4. Copy Client ID and Secret into `.env`

## Security

- `API_KEY`, `JWT_SECRET`, `GOOGLE_CLIENT_SECRET` in `.env` — never committed
- Google `id_token` verified server-side (issuer, audience, expiry, signature)
- JWT: HS256, short expiry, no sensitive data in payload beyond email/name
- Dual auth: operators can use API key; end users use Google SSO JWT
- Optional `ALLOWED_EMAILS` restricts who can log in via Google
- Concurrent stream limit prevents resource exhaustion
- YouTube URLs validated before subprocess invocation
- Filename in `Content-Disposition` sanitized (no path traversal)
- Do not log JWTs, API keys, or Google tokens

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

**Image contents:** `python:3.12-slim` + system `ffmpeg` + `yt-dlp` (pip) + FastAPI + `google-auth` + `python-jose` or `PyJWT`

No volume mount required — no persistent downloads or user database.

**Production:** Reverse proxy (Nginx/Caddy) for HTTPS in front of port 8000. HTTPS required for OAuth redirects in production.

## Error Handling

| Condition | Response |
|-----------|----------|
| Video unavailable / private | 502 with clear message |
| Non-YouTube URL | 400 |
| yt-dlp exceeds timeout | 502, process killed |
| Invalid credentials | 401 |
| Email not allowed | 403 |
| Concurrent limit hit | 429 |
| Invalid Google token | 401 |

**Logging:** Log request metadata (request ID, auth type, user email if JWT, URL, format, stream duration, errors). Never log secrets or tokens.

## Testing

**Local:**

```bash
docker compose up --build

curl http://localhost:8000/health

# API key (dev/scripts)
curl -H "X-API-Key: your-key" \
  "http://localhost:8000/search?q=lofi&limit=5"

# Google SSO → JWT (after obtaining id_token from Sign-In)
curl -X POST http://localhost:8000/auth/google \
  -H "Content-Type: application/json" \
  -d '{"id_token": "GOOGLE_ID_TOKEN"}'

curl -H "Authorization: Bearer YOUR_JWT" \
  "http://localhost:8000/search?q=lofi"

curl -H "Authorization: Bearer YOUR_JWT" \
  "http://localhost:8000/stream?url=https://www.youtube.com/watch?v=VIDEO_ID&format=mp3" \
  -o test.mp3

curl -H "Authorization: Bearer YOUR_JWT" http://localhost:8000/auth/me
```

**Verify:**

- Health returns 200 without auth
- Invalid Google token returns 401 on `POST /auth/google`
- Valid Google login returns JWT; `/auth/me` returns user info
- Search and stream work with Bearer JWT
- Search and stream still work with `X-API-Key`
- 401 without credentials on protected routes
- 403 when email not on allowlist (if configured)
- 429 when concurrent stream limit exceeded

## Future Extensions (Post-MVP)

- Android client with Google Sign-In SDK
- Refresh tokens or longer-lived sessions
- YouTube Data API v3 for improved search
- Async job model if streaming proves unreliable for mobile
- Per-user rate limiting keyed by JWT `sub`
- Admin role distinction beyond email allowlist
