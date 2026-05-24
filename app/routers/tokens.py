from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_api_token
from app.database import get_db
from app.dependencies import get_current_user
from app.models import APIToken, User
from app.schemas import APITokenCreate, APITokenCreated, APITokenResponse

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


@router.get("", response_model=list[APITokenResponse])
async def list_tokens(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(APIToken)
            .where(APIToken.user_id == user.id)
            .order_by(APIToken.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.post("", response_model=APITokenCreated, status_code=201)
async def create_token(
    data: APITokenCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    raw, hashed = generate_api_token()
    token = APIToken(
        user_id=user.id,
        name=data.name,
        token_hash=hashed,
        expires_at=data.expires_at.replace(tzinfo=None) if data.expires_at else None,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return APITokenCreated(
        id=token.id, name=token.name, is_active=token.is_active,
        created_at=token.created_at, expires_at=token.expires_at,
        last_used_at=token.last_used_at, raw_token=raw,
    )


@router.delete("/{token_id}", status_code=204)
async def revoke_token(
    token_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(APIToken).where(APIToken.id == token_id, APIToken.user_id == user.id)
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(404, "Token not found")
    token.is_active = False
    await db.commit()
