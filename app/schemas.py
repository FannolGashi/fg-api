import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_RESERVED = {"api", "ui", "static", "health", "webhook"}


def _clean_name(v: str) -> str:
    v = v.strip().lower()
    if not _NAME_RE.match(v):
        raise ValueError("Name must be 1–64 chars: letters, digits, underscore, hyphen")
    if v in _RESERVED:
        raise ValueError(f"'{v}' is reserved")
    return v


# ── Auth ──────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Endpoints ─────────────────────────────────────────────────────────────────

class EndpointCreate(BaseModel):
    name: str
    description: str = ""
    timeout: int = Field(default=30, ge=1, le=300)
    max_concurrent: int = Field(default=3, ge=1, le=20)
    response_type: str = "text/plain"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _clean_name(v)

    @field_validator("response_type")
    @classmethod
    def validate_response_type(cls, v: str) -> str:
        allowed = {"text/plain", "application/json", "text/html"}
        if v not in allowed:
            raise ValueError(f"Must be one of {allowed}")
        return v


class EndpointUpdate(BaseModel):
    description: Optional[str] = None
    timeout: Optional[int] = Field(default=None, ge=1, le=300)
    max_concurrent: Optional[int] = Field(default=None, ge=1, le=20)
    response_type: Optional[str] = None
    is_enabled: Optional[bool] = None


class ScriptStatus(BaseModel):
    has_script: bool = False
    venv_ready: bool = False
    has_requirements: bool = False
    venv_log: str = ""

    model_config = {"from_attributes": True}


class EndpointResponse(BaseModel):
    id: int
    name: str
    description: str
    is_enabled: bool
    timeout: int
    max_concurrent: int
    response_type: str
    created_at: datetime
    updated_at: datetime
    script: Optional[ScriptStatus] = None

    model_config = {"from_attributes": True}


# ── Logs ──────────────────────────────────────────────────────────────────────

class LogResponse(BaseModel):
    id: int
    endpoint_id: int
    endpoint_name: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    stdout: str
    stderr: str
    duration_ms: Optional[int] = None
    triggered_by: str
    timed_out: bool

    model_config = {"from_attributes": True}


# ── API Tokens ────────────────────────────────────────────────────────────────

class APITokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    expires_at: Optional[datetime] = None


class APITokenResponse(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class APITokenCreated(APITokenResponse):
    raw_token: str  # shown only once


# ── Schedules ─────────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    cron_expression: str = Field(description="5-field cron: min hour day month weekday")

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        if len(v.strip().split()) != 5:
            raise ValueError("Cron must have exactly 5 fields")
        return v.strip()


class ScheduleResponse(BaseModel):
    id: int
    endpoint_id: int
    cron_expression: str
    is_enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
