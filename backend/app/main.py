from fastapi import FastAPI

from app.routes.auth import router as auth_router
from app.routes.health import router as health_router
from app.routes.search import router as search_router
from app.routes.stream import router as stream_router

app = FastAPI(title="YT-DLP Backend", version="1.0.0")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(search_router)
app.include_router(stream_router)
