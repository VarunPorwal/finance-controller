"""PRD §5.2. No password column exists on ``users`` (db/models.py) — this is
the buildathon's identity model, not a placeholder: the demo token
(``AuthenticatedUser`` in ``api/deps.py``) is the primary path, and this
router exists so a real per-user JWT can also be minted, by email only,
for a user already seeded into the ``users`` table. Refresh tokens are JWTs
too (a distinct ``typ`` claim, longer TTL), since there is no session table
to back a revocable one without altering the schema after 28 Aug.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from api.deps import AuthenticatedUser, current_user, get_config, get_sessionmaker
from api.errors import ApiError
from db.models import User
from fc.config import Config

router = APIRouter(prefix="/auth", tags=["auth"])

_ALGORITHM = "HS256"
_ACCESS_TYPE = "access"
_REFRESH_TYPE = "refresh"


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class TokenOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    tenant_id: str
    role: str
    email: str
    display_name: str


def _mint(
    cfg: Config, *, user_id: str, tenant_id: str, role: str, email: str, display_name: str
) -> TokenOut:
    if not cfg.jwt_secret:
        raise ApiError(500, "auth not configured", "JWT_SECRET is not set")
    now = datetime.now(UTC)
    access_claims = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "email": email,
        "display_name": display_name,
        "typ": _ACCESS_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=cfg.jwt_ttl_minutes),
    }
    refresh_claims = {
        **access_claims,
        "typ": _REFRESH_TYPE,
        "exp": now + timedelta(days=cfg.refresh_ttl_days),
    }
    return TokenOut(
        access_token=jwt.encode(access_claims, cfg.jwt_secret, algorithm=_ALGORITHM),
        refresh_token=jwt.encode(refresh_claims, cfg.jwt_secret, algorithm=_ALGORITHM),
        expires_in=cfg.jwt_ttl_minutes * 60,
    )


@router.post("/token", response_model=TokenOut)
async def issue_token(body: TokenRequest, cfg: Config = Depends(get_config)) -> TokenOut:
    async with get_sessionmaker()() as session:
        user = await session.scalar(
            select(User).where(User.email == body.email, User.status == "active")
        )
    if user is None:
        raise ApiError(401, "unauthorized", "no active user with that email")
    return _mint(
        cfg,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        role=user.role,
        email=user.email,
        display_name=user.display_name,
    )


@router.post("/refresh", response_model=TokenOut)
async def refresh_token(body: RefreshRequest, cfg: Config = Depends(get_config)) -> TokenOut:
    if not cfg.jwt_secret:
        raise ApiError(500, "auth not configured", "JWT_SECRET is not set")
    try:
        claims = jwt.decode(body.refresh_token, cfg.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise ApiError(401, "unauthorized", f"invalid refresh token: {exc}") from exc
    if claims.get("typ") != _REFRESH_TYPE:
        raise ApiError(401, "unauthorized", "not a refresh token")
    return _mint(
        cfg,
        user_id=claims["sub"],
        tenant_id=claims["tenant_id"],
        role=claims["role"],
        email=claims.get("email", ""),
        display_name=claims.get("display_name", ""),
    )


@router.get("/me", response_model=MeOut)
async def me(user: AuthenticatedUser = Depends(current_user)) -> MeOut:
    return MeOut(**user.model_dump())


@router.post("/logout", status_code=204, response_class=Response)
async def logout(user: AuthenticatedUser = Depends(current_user)) -> Response:
    """Stateless JWTs have nothing server-side to revoke — the client
    discarding the token is the whole mechanism. This endpoint exists so the
    frontend has one call to make, not because the server does anything."""
    return Response(status_code=204)
