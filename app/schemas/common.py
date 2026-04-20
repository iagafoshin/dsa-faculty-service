from typing import Any

from pydantic import BaseModel


class Error(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class ReadyChecks(BaseModel):
    db: str


class ReadyResponse(BaseModel):
    status: str
    checks: ReadyChecks


class Campus(BaseModel):
    campus_id: str
    campus_name: str


class PublicationTypeMeta(BaseModel):
    code: str
    label: str
