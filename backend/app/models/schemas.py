from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class HealthResponse(BaseModel):
    status: str = "ok"


class UserInfo(BaseModel):
    sub: str
    email: str
    name: str | None = None
    picture: str | None = None


class GoogleTokenRequest(BaseModel):
    id_token: str = Field(min_length=10)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserInfo


class AuthMeResponse(BaseModel):
    auth_type: Literal["jwt", "api_key"]
    user: UserInfo | None = None


class SearchResultItem(BaseModel):
    id: str
    title: str
    url: HttpUrl
    duration: int | None = None
    thumbnail: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
