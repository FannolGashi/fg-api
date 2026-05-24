import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import hash_password, verify_password
from app.config import settings
from app.database import init_db
from app.services.scheduler import get_scheduler, load_all_schedules

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FG API",
    description="Self-hosted dynamic script execution platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_static = Path(__file__).parent / "static"
_static.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    await _ensure_admin_user()
    await load_all_schedules()
    get_scheduler().start()
    logger.info("FG API started — admin user: %s", settings.admin_username)


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)


async def _ensure_admin_user() -> None:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models import User

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == settings.admin_username))
        user = result.scalar_one_or_none()
        if not user:
            db.add(User(
                username=settings.admin_username,
                hashed_password=hash_password(settings.admin_password),
            ))
            await db.commit()
            logger.info("Created admin user '%s'", settings.admin_username)
        elif not verify_password(settings.admin_password, user.hashed_password):
            # Sync password if env var changed
            user.hashed_password = hash_password(settings.admin_password)
            await db.commit()
            logger.info("Updated password for '%s'", settings.admin_username)


# ── Routers — order matters: catch-all /execute must be last ──────────────────

from app.routers import auth, endpoints, execute, logs, tokens, ui  # noqa: E402

app.include_router(ui.router)         # /  /ui/*
app.include_router(auth.router)       # /api/auth/*
app.include_router(endpoints.router)  # /api/endpoints/*
app.include_router(logs.router)       # /api/logs/*
app.include_router(tokens.router)     # /api/tokens/*
app.include_router(execute.router)    # /{name}  /webhook/{name}  ← LAST


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
