from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id             = Column(Integer, primary_key=True)
    username       = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password= Column(String(128), nullable=False)
    is_active      = Column(Boolean, default=True, nullable=False)
    created_at     = Column(DateTime, default=_now, nullable=False)

    tokens = relationship("APIToken", back_populates="user", cascade="all, delete-orphan")


class APIToken(Base):
    __tablename__ = "api_tokens"

    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    name         = Column(String(64), nullable=False)
    token_hash   = Column(String(64), unique=True, nullable=False)  # SHA-256
    is_active    = Column(Boolean, default=True, nullable=False)
    created_at   = Column(DateTime, default=_now, nullable=False)
    expires_at   = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="tokens")


class Endpoint(Base):
    __tablename__ = "endpoints"

    id              = Column(Integer, primary_key=True)
    name            = Column(String(128), unique=True, nullable=False, index=True)
    description     = Column(Text, default="", nullable=False)
    is_enabled      = Column(Boolean, default=True, nullable=False)
    timeout         = Column(Integer, default=30, nullable=False)
    max_concurrent  = Column(Integer, default=3, nullable=False)
    response_type   = Column(String(32), default="text/plain", nullable=False)
    created_at      = Column(DateTime, default=_now, nullable=False)
    updated_at      = Column(DateTime, default=_now, nullable=False)

    script        = relationship("Script",       back_populates="endpoint", uselist=False, cascade="all, delete-orphan")
    logs          = relationship("ExecutionLog", back_populates="endpoint", cascade="all, delete-orphan")
    scheduled_job = relationship("ScheduledJob", back_populates="endpoint", uselist=False, cascade="all, delete-orphan")


class Script(Base):
    __tablename__ = "scripts"

    id               = Column(Integer, primary_key=True)
    endpoint_id      = Column(Integer, ForeignKey("endpoints.id"), unique=True, nullable=False)
    filename         = Column(String(256), nullable=False)
    has_requirements = Column(Boolean, default=False, nullable=False)
    venv_ready       = Column(Boolean, default=False, nullable=False)
    venv_log         = Column(Text, default="", nullable=False)
    created_at       = Column(DateTime, default=_now, nullable=False)
    updated_at       = Column(DateTime, default=_now, nullable=False)

    endpoint = relationship("Endpoint", back_populates="script")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id           = Column(Integer, primary_key=True)
    endpoint_id  = Column(Integer, ForeignKey("endpoints.id"), nullable=False)
    started_at   = Column(DateTime, default=_now, nullable=False)
    finished_at  = Column(DateTime, nullable=True)
    exit_code    = Column(Integer, nullable=True)
    stdout       = Column(Text, default="", nullable=False)
    stderr       = Column(Text, default="", nullable=False)
    duration_ms  = Column(Integer, nullable=True)
    triggered_by = Column(String(32), default="http", nullable=False)
    timed_out    = Column(Boolean, default=False, nullable=False)

    endpoint = relationship("Endpoint", back_populates="logs")


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id              = Column(Integer, primary_key=True)
    endpoint_id     = Column(Integer, ForeignKey("endpoints.id"), unique=True, nullable=False)
    cron_expression = Column(String(64), nullable=False)
    is_enabled      = Column(Boolean, default=True, nullable=False)
    last_run_at     = Column(DateTime, nullable=True)
    next_run_at     = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=_now, nullable=False)

    endpoint = relationship("Endpoint", back_populates="scheduled_job")
