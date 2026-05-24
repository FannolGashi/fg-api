"""
APScheduler-based cron execution.
All scheduled jobs are loaded from the DB on startup and kept in sync via the CRUD API.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def _job_id(endpoint_id: int) -> str:
    return f"ep_{endpoint_id}"


async def _run_scheduled(endpoint_id: int) -> None:
    from app.database import AsyncSessionLocal
    from app.models import Endpoint, ExecutionLog, ScheduledJob
    from app.services import executor
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Endpoint)
            .options(selectinload(Endpoint.script))
            .where(Endpoint.id == endpoint_id)
        )
        endpoint = result.scalar_one_or_none()
        if not endpoint or not endpoint.is_enabled:
            return
        if not endpoint.script or not endpoint.script.venv_ready:
            logger.warning("Skipped scheduled run for '%s': not ready", endpoint.name)
            return

        exec_result = await executor.execute(endpoint)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        db.add(ExecutionLog(
            endpoint_id=endpoint.id,
            finished_at=now,
            exit_code=exec_result.exit_code,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            duration_ms=exec_result.duration_ms,
            triggered_by="cron",
            timed_out=exec_result.timed_out,
        ))

        job_result = await db.execute(
            select(ScheduledJob).where(ScheduledJob.endpoint_id == endpoint_id)
        )
        job = job_result.scalar_one_or_none()
        if job:
            job.last_run_at = now
        await db.commit()
        logger.info("Cron: endpoint=%s exit=%s %dms",
                    endpoint.name, exec_result.exit_code, exec_result.duration_ms)


def schedule_endpoint(endpoint_id: int, cron_expression: str) -> None:
    scheduler = get_scheduler()
    jid = _job_id(endpoint_id)
    parts = cron_expression.split()
    trigger = CronTrigger(
        minute=parts[0], hour=parts[1],
        day=parts[2], month=parts[3], day_of_week=parts[4],
        timezone="UTC",
    )
    if scheduler.get_job(jid):
        scheduler.reschedule_job(jid, trigger=trigger)
    else:
        scheduler.add_job(_run_scheduled, trigger, id=jid,
                          args=[endpoint_id], replace_existing=True)
    logger.info("Scheduled endpoint_id=%s cron='%s'", endpoint_id, cron_expression)


def unschedule_endpoint(endpoint_id: int) -> None:
    scheduler = get_scheduler()
    jid = _job_id(endpoint_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)


async def load_all_schedules() -> None:
    from app.database import AsyncSessionLocal
    from app.models import ScheduledJob
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledJob).where(ScheduledJob.is_enabled.is_(True))
        )
        jobs = result.scalars().all()
        for job in jobs:
            schedule_endpoint(job.endpoint_id, job.cron_expression)
    logger.info("Loaded %d scheduled jobs from DB", len(jobs))
