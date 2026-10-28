"""Schemas for attendance registers (D1)."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The largest register that can be saved at once (far above any real class).
MAX_MARKS_PER_REGISTER = 200

Status = Literal["present", "absent", "late"]
Reason = Literal["sick", "permission", "unknown"]


class MarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID
    status: Status
    reason: Reason | None = None

    @model_validator(mode="after")
    def _reason_matches_status(self):
        if self.status == "absent" and self.reason is None:
            raise ValueError("Choose a reason for each absence: sick, permission or unknown.")
        if self.status != "absent" and self.reason is not None:
            raise ValueError("Only an absence can have a reason.")
        return self


class SaveRegisterRequest(BaseModel):
    """The whole register: one mark for every student in it."""

    model_config = ConfigDict(extra="forbid")

    marks: list[MarkIn] = Field(min_length=1, max_length=MAX_MARKS_PER_REGISTER)

    @field_validator("marks")
    @classmethod
    def _one_mark_per_student(cls, value: list[MarkIn]) -> list[MarkIn]:
        ids = [mark.student_id for mark in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Each student may appear only once.")
        return value


class TermSummaryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: int = Field(ge=1, le=3)


class OverviewQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date | None = None
