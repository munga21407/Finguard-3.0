import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from src.domains.identity.models import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=255)


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    is_verified: bool | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Internal service return type — carries both tokens so the router can set
    the refresh token as an HttpOnly cookie and return only the access token."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    """HTTP response body for POST /token and POST /token/refresh.

    The refresh token is delivered as an HttpOnly, SameSite=Strict cookie by
    the router — it is intentionally absent from this body so it cannot be
    exfiltrated via XSS.
    """
    access_token: str
    token_type: str = "bearer"
