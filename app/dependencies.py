from datetime import datetime, timezone
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import decode_access_token, hash_api_token
from app.database import get_db
from app.models import APIToken, User

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = (credentials.credentials if credentials else None) or access_token
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    # Try JWT session token
    payload = decode_access_token(token)
    if payload and (username := payload.get("sub")):
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user

    # Try long-lived API token
    token_hash = hash_api_token(token)
    result = await db.execute(
        select(APIToken).where(
            APIToken.token_hash == token_hash,
            APIToken.is_active.is_(True),
        )
    )
    api_token = result.scalar_one_or_none()
    if api_token:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if api_token.expires_at and api_token.expires_at < now:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
        result2 = await db.execute(select(User).where(User.id == api_token.user_id))
        user = result2.scalar_one_or_none()
        if user and user.is_active:
            api_token.last_used_at = now
            await db.commit()
            return user

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    try:
        return await get_current_user(request, credentials, access_token, db)
    except HTTPException:
        return None
