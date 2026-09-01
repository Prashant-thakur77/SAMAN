"""Pydantic request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


# --- auth ---


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    cpse_code: str | None = None


class DemoUser(BaseModel):
    """Login-screen picker entry. Carries no secret — the password is `demo`."""

    email: str
    name: str
    role: str
    cpse_code: str | None = None


# --- ingest ---


class RejectedRow(BaseModel):
    row_number: int
    reason: str
    raw: dict[str, str]


class SampleNormalization(BaseModel):
    legacy_code: str
    original: str
    normalized: str
    class_code: str
    class_confidence: float
    attrs: dict


class IngestReport(BaseModel):
    cpse_code: str
    dry_run: bool
    rows_read: int
    rows_accepted: int
    rows_rejected: int
    duplicates_in_file: int
    already_present: int
    column_mapping: dict[str, str]
    unmapped_columns: list[str] = Field(default_factory=list)
    rejected: list[RejectedRow] = Field(default_factory=list)
    samples: list[SampleNormalization] = Field(default_factory=list)


# --- pipeline ---


class PipelineStatusOut(BaseModel):
    state: str
    stage: str | None
    stages_done: list[str]
    rows_done: int
    rows_total: int
    percent: float
    eta_seconds: float | None
    elapsed_seconds: float | None
    error: str | None
