"""Schemas for student records."""

import uuid
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.student import MAX_ADMISSION_NUMBER_LENGTH, MAX_STUDENT_NAME_LENGTH

MAX_AGE_YEARS = 30
MAX_PER_PAGE = 100
MAX_SEARCH_LENGTH = 100


def _not_blank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Must not be blank.")
    return value


def _plausible_birth_date(value: date | None) -> date | None:
    if value is None:
        return None
    # One day of slack, so a date that is already "today" somewhere in the
    # world is not refused because the server runs on UTC.
    today = datetime.now(UTC).date()
    if value > today + timedelta(days=1):
        raise ValueError("Date of birth cannot be in the future.")
    try:
        oldest = today.replace(year=today.year - MAX_AGE_YEARS)
    except ValueError:  # Today is 29 February.
        oldest = today.replace(year=today.year - MAX_AGE_YEARS, day=28)
    if value < oldest:
        raise ValueError(f"Date of birth cannot be more than {MAX_AGE_YEARS} years ago.")
    return value


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    admission_number: str
    full_name: str
    date_of_birth: date | None
    is_active: bool


class CreateStudentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admission_number: str = Field(min_length=1, max_length=MAX_ADMISSION_NUMBER_LENGTH)
    full_name: str = Field(min_length=1, max_length=MAX_STUDENT_NAME_LENGTH)
    date_of_birth: date | None = None

    _trim = field_validator("admission_number", "full_name")(_not_blank)
    _check_birth_date = field_validator("date_of_birth")(_plausible_birth_date)


class UpdateStudentRequest(BaseModel):
    """Only the fields sent are changed. `date_of_birth` may be cleared with null."""

    model_config = ConfigDict(extra="forbid")

    admission_number: str | None = Field(
        default=None, min_length=1, max_length=MAX_ADMISSION_NUMBER_LENGTH
    )
    full_name: str | None = Field(default=None, min_length=1, max_length=MAX_STUDENT_NAME_LENGTH)
    date_of_birth: date | None = None

    @field_validator("admission_number", "full_name")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Must not be null.")
        return _not_blank(value)

    _check_birth_date = field_validator("date_of_birth")(_plausible_birth_date)

    @model_validator(mode="after")
    def _something_to_change(self) -> "UpdateStudentRequest":
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        return self


class StudentListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, le=10_000)
    per_page: int = Field(default=50, ge=1, le=MAX_PER_PAGE)
    # Matches part of the name or admission number, ignoring letter case.
    q: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    # Only active students with no class in this school year (for enrolling).
    not_enrolled_in: uuid.UUID | None = None
