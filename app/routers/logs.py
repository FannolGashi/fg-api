from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import ExecutionLog
from app.schemas import LogResponse

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=list[LogResponse])
async def list_logs(
    endpoint_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(ExecutionLog)
        .options(selectinload(ExecutionLog.endpoint))
        .order_by(desc(ExecutionLog.started_at))
        .limit(limit)
    )
    if endpoint_id is not None:
        q = q.where(ExecutionLog.endpoint_id == endpoint_id)
    rows = (await db.execute(q)).scalars().all()

    out = []
    for row in rows:
        d = LogResponse.model_validate(row)
        d.endpoint_name = row.endpoint.name if row.endpoint else None
        out.append(d)
    return out


@router.get("/{log_id}", response_model=LogResponse)
async def get_log(log_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExecutionLog)
        .options(selectinload(ExecutionLog.endpoint))
        .where(ExecutionLog.id == log_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Log not found")
    d = LogResponse.model_validate(row)
    d.endpoint_name = row.endpoint.name if row.endpoint else None
    return d
