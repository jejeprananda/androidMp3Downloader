from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.models.schemas import UserInfo
from app.services.google_auth import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    auth_type: Literal["jwt", "api_key"]
    user: UserInfo | None = None


def _validate_api_key(api_key: str | None, settings: Settings) -> bool:
    return api_key is not None and api_key == settings.api_key


async def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> AuthContext:
    if credentials is not None and credentials.credentials:
        user = decode_access_token(credentials.credentials, settings)
        return AuthContext(auth_type="jwt", user=user)

    if _validate_api_key(x_api_key, settings):
        return AuthContext(auth_type="api_key", user=None)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
