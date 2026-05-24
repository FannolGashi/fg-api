"""
Catch-all execution router — placed last so it never shadows /api/* or /ui/*.

GET  /{endpoint_name}          — HTTP trigger (public)
POST /webhook/{endpoint_name}  — webhook trigger (public)
"""

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Endpoint, ExecutionLog
from app.services import executor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["execute"])

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


async def _run_endpoint(name: str, triggered_by: str, db: AsyncSession) -> Response:
    if not _NAME_RE.match(name):
        raise HTTPException(404, "Not found")

    result = await db.execute(
        select(Endpoint)
        .options(selectinload(Endpoint.script))
        .where(Endpoint.name == name)
    )
    ep = result.scalar_one_or_none()

    if not ep:
        raise HTTPException(404, f"Endpoint '{name}' not found")
    if not ep.is_enabled:
        raise HTTPException(503, "Endpoint is disabled")
    if not ep.script:
        raise HTTPException(503, "No script uploaded yet")
    if not ep.script.venv_ready:
        raise HTTPException(503, "Venv not ready — check logs or rebuild")

    res = await executor.execute(ep)

    # Concurrency-saturated or setup failure
    if res.error and not res.stdout and not res.stderr:
        code = 429 if "concurrent" in (res.error or "") else 500
        raise HTTPException(code, res.error)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(ExecutionLog(
        endpoint_id=ep.id,
        finished_at=now,
        exit_code=res.exit_code,
        stdout=res.stdout,
        stderr=res.stderr,
        duration_ms=res.duration_ms,
        triggered_by=triggered_by,
        timed_out=res.timed_out,
    ))
    await db.commit()

    body = res.stdout or res.stderr or ""
    status_code = 200 if res.exit_code == 0 and not res.timed_out else 500
    return Response(content=body, media_type=ep.response_type, status_code=status_code)


@router.get("/{endpoint_name}")
async def execute_endpoint(endpoint_name: str, db: AsyncSession = Depends(get_db)):
    return await _run_endpoint(endpoint_name, "http", db)


@router.post("/webhook/{endpoint_name}")
async def webhook_trigger(
    endpoint_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await _run_endpoint(endpoint_name, "webhook", db)
