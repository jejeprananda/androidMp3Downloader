# YT-DLP Backend API

Dockerized FastAPI backend for YouTube search and MP3/MP4 streaming via yt-dlp.

## Quick start

```bash
cd backend
cp .env.example .env
# Edit .env with your API_KEY, Google OAuth credentials, and JWT_SECRET

docker compose up --build
```

API runs at `http://localhost:8000`.

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | No |
| POST | `/auth/google` | No |
| GET | `/auth/google/login` | No |
| GET | `/auth/google/callback` | No |
| GET | `/auth/me` | Yes |
| GET | `/search?q=` | Yes |
| GET | `/stream?url=&format=` | Yes |

Auth: `Authorization: Bearer <jwt>` or `X-API-Key: <key>`.

## Example

```bash
curl http://localhost:8000/health

curl -H "X-API-Key: your-key" \
  "http://localhost:8000/search?q=lofi&limit=5"
```

See `docs/superpowers/specs/2026-08-16-ytdl-backend-design.md` for full design.
