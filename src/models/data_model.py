from __future__ import annotations, nested_scopes

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID,uuid4

from pydantic import BaseModel, Field,ConfigDict, field_validator


class SourceMode(str,int):
    HTTP = "http"
    BROWSER = "browser"


class Checkpoint(str,Enum):
    PENDING = "pending"
    SUCCESS = "success"
    NEEDS_RETRY = "needs_retry"
    FAILED = "failed"

class YieldRecord(BaseModel):

    model_config = ConfigDict(str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)

    year: int = Field(..., ge=2018, le=2026)
    semester: str = Field(...,ge=1, le=2)
    region_id: int = Field(..., ge=0)
    region_name: str = Field(..., min_length=1)
    province_id: int = Field(..., ge=0)
    province_name: str = Field(..., min_length=1)
    municipality: str = Field(..., min_length=1)

    