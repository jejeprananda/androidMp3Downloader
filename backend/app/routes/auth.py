from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.dependencies.auth import AuthContext, get_auth_context
from app.models.schemas import AuthMeResponse, AuthTokenResponse, GoogleTokenRequest
from app.services.google_auth import (
    build_google_login_url,
    create_access_token,
    exchange_code_for_user,
    generate_oauth_state,
    verify_google_id_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_auth_response(user, settings: Settings) -> AuthTokenResponse:
    access_token, expires_in = create_access_token(user, settings)
    return AuthTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=user.to_user_info(),
    )


def _encode_oauth_state(settings: Settings) -> str:
    return jwt.encode(
        {"purpose": "google_oauth", "nonce": generate_oauth_state()},
        settings.jwt_secret,
        algorithm="HS256",
    )


def _verify_oauth_state(state: str, settings: Settings) -> None:
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")

    if payload.get("purpose") != "google_oauth":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")


@router.post("/google", response_model=AuthTokenResponse)
async def auth_google_token_exchange(
    body: GoogleTokenRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthTokenResponse:
    user = verify_google_id_token(body.id_token, settings)
    return _build_auth_response(user, settings)


@router.get("/google/login")
async def auth_google_login(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    state = _encode_oauth_state(settings)
    login_url = build_google_login_url(settings, state)
    return RedirectResponse(url=login_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/google/callback", response_model=AuthTokenResponse)
async def auth_google_callback(
    code: Annotated[str, Query(min_length=1)],
    state: Annotated[str, Query(min_length=1)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthTokenResponse:
    _verify_oauth_state(state, settings)
    user = await exchange_code_for_user(code, settings)
    return _build_auth_response(user, settings)


@router.get("/me", response_model=AuthMeResponse)
async def auth_me(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthMeResponse:
    return AuthMeResponse(auth_type=auth.auth_type, user=auth.user)
