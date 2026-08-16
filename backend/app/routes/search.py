from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import Settings, get_settings
from app.dependencies.auth import AuthContext, get_auth_context
from app.models.schemas import SearchResponse
from app.services.ytdlp import YtdlpError, search_videos

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def search(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    q: Annotated[str, Query(min_length=2)],
    limit: Annotated[int | None, Query(ge=1)] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> SearchResponse:
    del auth  # auth enforced by dependency

    effective_limit = limit or settings.search_limit_default
    effective_limit = min(effective_limit, settings.search_limit_max)

    try:
        results = await search_videos(q, effective_limit, settings)
    except YtdlpError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    return SearchResponse(results=results)
