from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user_optional
from app.models import Endpoint, ExecutionLog, User

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
templates.env.globals["app_name"] = settings.app_name


def _ctx(request: Request, user, **kw):
    return {"request": request, "user": user, **kw}


@router.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/ui")


@router.get("/ui", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_optional),
):
    endpoints = (
        await db.execute(
            select(Endpoint).options(selectinload(Endpoint.script)).order_by(Endpoint.name)
        )
    ).scalars().all()

    recent_logs = (
        await db.execute(
            select(ExecutionLog)
            .options(selectinload(ExecutionLog.endpoint))
            .order_by(desc(ExecutionLog.started_at))
            .limit(20)
        )
    ).scalars().all()

    return templates.TemplateResponse("dashboard.html", _ctx(
        request, user,
        endpoints=endpoints,
        recent_logs=recent_logs,
        total=len(endpoints),
        active=sum(1 for e in endpoints if e.is_enabled),
        active_page="dashboard",
    ))


@router.get("/ui/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user: User = Depends(get_current_user_optional),
):
    if user:
        return RedirectResponse("/ui")
    return templates.TemplateResponse("login.html", _ctx(request, user))


@router.get("/ui/endpoints", response_class=HTMLResponse)
async def endpoints_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse("/ui/login")
    endpoints = (
        await db.execute(
            select(Endpoint).options(selectinload(Endpoint.script)).order_by(Endpoint.name)
        )
    ).scalars().all()
    return templates.TemplateResponse("endpoints.html", _ctx(
        request, user, endpoints=endpoints, active_page="endpoints"
    ))


@router.get("/ui/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_optional),
):
    endpoints = (await db.execute(select(Endpoint).order_by(Endpoint.name))).scalars().all()
    logs = (
        await db.execute(
            select(ExecutionLog)
            .options(selectinload(ExecutionLog.endpoint))
            .order_by(desc(ExecutionLog.started_at))
            .limit(100)
        )
    ).scalars().all()
    return templates.TemplateResponse("logs.html", _ctx(
        request, user, endpoints=endpoints, logs=logs, active_page="logs"
    ))
