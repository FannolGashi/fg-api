import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.dependencies import get_current_user
from app.models import Endpoint, ScheduledJob, Script, User
from app.schemas import (
    EndpointCreate,
    EndpointResponse,
    EndpointUpdate,
    ScheduleCreate,
    ScheduleResponse,
)
from app.services import executor as exec_svc
from app.services import venv_manager
from app.services.scheduler import schedule_endpoint, unschedule_endpoint

router = APIRouter(prefix="/api/endpoints", tags=["endpoints"])
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_ep(endpoint_id: int, db: AsyncSession) -> Endpoint:
    result = await db.execute(
        select(Endpoint)
        .options(selectinload(Endpoint.script))
        .where(Endpoint.id == endpoint_id)
    )
    ep = result.scalar_one_or_none()
    if not ep:
        raise HTTPException(404, "Endpoint not found")
    return ep


# ── List / Get (public) ───────────────────────────────────────────────────────

@router.get("", response_model=list[EndpointResponse])
async def list_endpoints(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Endpoint).options(selectinload(Endpoint.script)).order_by(Endpoint.name)
        )
    ).scalars().all()
    return rows


@router.get("/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(endpoint_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_ep(endpoint_id, db)


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_model=EndpointResponse, status_code=201)
async def create_endpoint(
    data: EndpointCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = (await db.execute(select(Endpoint).where(Endpoint.name == data.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Endpoint '{data.name}' already exists")
    ep = Endpoint(**data.model_dump())
    db.add(ep)
    await db.commit()
    await db.refresh(ep)
    ep = await _get_ep(ep.id, db)
    logger.info("Created endpoint '%s' by user '%s'", ep.name, user.username)
    return ep


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/{endpoint_id}", response_model=EndpointResponse)
async def update_endpoint(
    endpoint_id: int,
    data: EndpointUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ep = await _get_ep(endpoint_id, db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ep, field, value)
    ep.updated_at = _now()
    if data.max_concurrent is not None:
        exec_svc.invalidate_semaphore(endpoint_id)
    await db.commit()
    return await _get_ep(endpoint_id, db)


# ── Toggle ────────────────────────────────────────────────────────────────────

@router.post("/{endpoint_id}/toggle", response_model=EndpointResponse)
async def toggle_endpoint(
    endpoint_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ep = await _get_ep(endpoint_id, db)
    ep.is_enabled = not ep.is_enabled
    ep.updated_at = _now()
    await db.commit()
    return await _get_ep(endpoint_id, db)


# ── Manual run ───────────────────────────────────────────────────────────────

@router.post("/{endpoint_id}/run")
async def run_endpoint_now(
    endpoint_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Execute the script immediately and return full output. Requires auth."""
    ep = await _get_ep(endpoint_id, db)

    if not ep.script:
        raise HTTPException(422, "No script uploaded yet")
    if not ep.script.venv_ready:
        raise HTTPException(422, "Venv not ready — upload a script or trigger a rebuild first")

    res = await exec_svc.execute(ep)

    if res.error and not res.stdout and not res.stderr:
        raise HTTPException(429 if "concurrent" in (res.error or "") else 500, res.error)

    now = _now()
    from app.models import ExecutionLog
    db.add(ExecutionLog(
        endpoint_id=ep.id,
        finished_at=now,
        exit_code=res.exit_code,
        stdout=res.stdout,
        stderr=res.stderr,
        duration_ms=res.duration_ms,
        triggered_by="manual",
        timed_out=res.timed_out,
    ))
    await db.commit()

    return {
        "endpoint":    ep.name,
        "exit_code":   res.exit_code,
        "timed_out":   res.timed_out,
        "duration_ms": res.duration_ms,
        "stdout":      res.stdout,
        "stderr":      res.stderr,
    }


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{endpoint_id}", status_code=204)
async def delete_endpoint(
    endpoint_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ep = await _get_ep(endpoint_id, db)
    name = ep.name
    unschedule_endpoint(endpoint_id)
    await db.delete(ep)
    await db.commit()
    venv_manager.delete_endpoint_files(name)
    logger.info("Deleted endpoint '%s'", name)


# ── Script upload ─────────────────────────────────────────────────────────────

@router.post("/{endpoint_id}/script", status_code=202)
async def upload_script(
    endpoint_id: int,
    background_tasks: BackgroundTasks,
    script_file: UploadFile = File(...),
    requirements_file: Optional[UploadFile] = File(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ep = await _get_ep(endpoint_id, db)

    content = await script_file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "Script too large (max 10 MB)")

    script_dir = venv_manager.get_script_dir(ep.name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "script.py").write_bytes(content)

    has_req = False
    if requirements_file:
        req_bytes = await requirements_file.read()
        if len(req_bytes) > 1_048_576:
            raise HTTPException(413, "requirements.txt too large (max 1 MB)")
        (script_dir / "requirements.txt").write_bytes(req_bytes)
        has_req = True

    # Upsert Script row
    result = await db.execute(select(Script).where(Script.endpoint_id == endpoint_id))
    row = result.scalar_one_or_none()
    if row:
        row.has_requirements = has_req
        row.venv_ready = False
        row.venv_log = "Rebuilding venv..."
        row.updated_at = _now()
    else:
        row = Script(endpoint_id=endpoint_id, filename="script.py",
                     has_requirements=has_req, venv_ready=False,
                     venv_log="Setting up venv...")
        db.add(row)
    await db.commit()

    background_tasks.add_task(_setup_venv_bg, endpoint_id, ep.name, has_req)
    return {"message": "Script uploaded. Venv setup started in background."}


async def _setup_venv_bg(endpoint_id: int, name: str, has_requirements: bool) -> None:
    ok, log_text = await venv_manager.rebuild_venv(name, has_requirements)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Script).where(Script.endpoint_id == endpoint_id))
        row = result.scalar_one_or_none()
        if row:
            row.venv_ready = ok
            row.venv_log = log_text
            row.updated_at = _now()
            await db.commit()
    logger.info("Venv setup endpoint='%s' ok=%s", name, ok)


# ── Rebuild venv ──────────────────────────────────────────────────────────────

@router.post("/{endpoint_id}/rebuild-venv", status_code=202)
async def rebuild_venv(
    endpoint_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ep = await _get_ep(endpoint_id, db)
    if not ep.script:
        raise HTTPException(404, "No script uploaded")
    ep.script.venv_ready = False
    ep.script.venv_log = "Rebuilding..."
    await db.commit()
    background_tasks.add_task(_setup_venv_bg, endpoint_id, ep.name, ep.script.has_requirements)
    return {"message": "Venv rebuild started"}


# ── Schedule ──────────────────────────────────────────────────────────────────

@router.get("/{endpoint_id}/schedule", response_model=Optional[ScheduleResponse])
async def get_schedule(
    endpoint_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ScheduledJob).where(ScheduledJob.endpoint_id == endpoint_id)
    )
    return result.scalar_one_or_none()


@router.put("/{endpoint_id}/schedule", response_model=ScheduleResponse)
async def set_schedule(
    endpoint_id: int,
    data: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_ep(endpoint_id, db)
    result = await db.execute(
        select(ScheduledJob).where(ScheduledJob.endpoint_id == endpoint_id)
    )
    job = result.scalar_one_or_none()
    if job:
        job.cron_expression = data.cron_expression
        job.is_enabled = True
    else:
        job = ScheduledJob(endpoint_id=endpoint_id, cron_expression=data.cron_expression)
        db.add(job)
    await db.commit()
    await db.refresh(job)
    schedule_endpoint(endpoint_id, data.cron_expression)
    return job


@router.delete("/{endpoint_id}/schedule", status_code=204)
async def delete_schedule(
    endpoint_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ScheduledJob).where(ScheduledJob.endpoint_id == endpoint_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "No schedule found")
    unschedule_endpoint(endpoint_id)
    await db.delete(job)
    await db.commit()
