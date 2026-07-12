from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


WorkStatus = Literal["START", "RUNNING", "DONE", "FAIL", "STOP"]
ErrorLevel = Literal["INFO", "WARN", "ERROR", "FATAL"]
ProcessStep = Literal["PICK", "PLACE"]


class PaginationParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class WorkHistoryCreate(BaseModel):
    die_serial_number: str = Field(..., min_length=1, max_length=100)
    stack_count: int = Field(default=4, ge=4, le=16)
    status: WorkStatus = "START"
    start_time: datetime | None = None

    @field_validator("die_serial_number")
    @classmethod
    def strip_die_serial_number(cls, v: str):
        return v.strip()


class WorkHistoryUpdate(BaseModel):
    status: WorkStatus | None = None
    end_time: datetime | None = None


class WorkHistoryResponse(BaseModel):
    history_id: int
    die_serial_number: str
    stack_count: int
    place_completion_times: list[datetime] = Field(default_factory=list)
    start_time: datetime
    end_time: datetime | None = None
    status: str


class PlaceCompletionCreate(BaseModel):
    chip_index: int = Field(..., ge=1, le=16)
    completed_at: datetime | None = None


class RobotErrorLogCreate(BaseModel):
    error_level: ErrorLevel
    error_code: str | None = Field(default=None, max_length=50)
    detail: str | None = None
    history_id: int | None = Field(default=None, ge=1)
    error_time: datetime | None = None

    @field_validator("error_code")
    @classmethod
    def strip_error_code(cls, v: str | None):
        return v.strip() if v else v


class RobotErrorLogResponse(BaseModel):
    log_id: int
    error_time: datetime
    error_level: str
    error_code: str | None = None
    detail: str | None = None
    history_id: int | None = None


class VisionAlignLogCreate(BaseModel):
    history_id: int = Field(..., ge=1)
    process_step: ProcessStep
    camera_type: str = Field(..., min_length=1, max_length=50)
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_theta: float = 0.0
    created_at: datetime | None = None

    @field_validator("camera_type")
    @classmethod
    def strip_camera_type(cls, v: str):
        return v.strip()


class VisionAlignLogResponse(BaseModel):
    align_id: int
    history_id: int
    process_step: str
    camera_type: str
    offset_x: float
    offset_y: float
    offset_theta: float
    created_at: datetime


class WorkHistoryDetailResponse(WorkHistoryResponse):
    error_logs: list[RobotErrorLogResponse]
    vision_align_logs: list[VisionAlignLogResponse]
