from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class HospitalRow(BaseModel):
    """A validated hospital row parsed from the uploaded CSV."""

    row: int = Field(..., ge=1, description="1-based data row number in the CSV")
    name: str = Field(..., min_length=1)
    address: str = Field(..., min_length=1)
    phone: Optional[str] = None

    @field_validator("name", "address", mode="before")
    @classmethod
    def strip_whitespace(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value

    @field_validator("phone", mode="before")
    @classmethod
    def empty_phone_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value or None


class RowStatus(str, Enum):
    PENDING = "pending"
    CREATED = "created"
    CREATED_AND_ACTIVATED = "created_and_activated"
    FAILED = "failed"


class RowResult(BaseModel):
    row: int
    hospital_id: Optional[int] = None
    name: str
    status: RowStatus = RowStatus.PENDING
    error: Optional[str] = None


class BatchState(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


class BatchRecord(BaseModel):
    """In-memory record tracking the lifecycle of one bulk upload."""

    batch_id: str
    state: BatchState = BatchState.PROCESSING
    total_hospitals: int
    processed_hospitals: int = 0
    failed_hospitals: int = 0
    batch_activated: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processing_time_seconds: Optional[float] = None
    results: list[RowResult] = Field(default_factory=list)
    # Original rows kept so failed ones can be resumed later.
    rows: list[HospitalRow] = Field(default_factory=list)


class BulkProcessResponse(BaseModel):
    batch_id: str
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    processing_time_seconds: float
    batch_activated: bool
    hospitals: list[RowResult]


class BatchProgressResponse(BaseModel):
    batch_id: str
    state: BatchState
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    progress_percent: float
    batch_activated: bool
    created_at: datetime
    processing_time_seconds: Optional[float] = None


class CsvRowError(BaseModel):
    row: int
    error: str


class CsvValidationResponse(BaseModel):
    valid: bool
    total_rows: int
    valid_rows: int
    errors: list[CsvRowError]
