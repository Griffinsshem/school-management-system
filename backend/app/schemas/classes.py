"""Schemas for classes and class teachers (C2).

Whether a grade exists in a school year depends on the year's dates, so that
rule is checked in app/api/v1/classes.py, not here.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.school_class import GRADES, MAX_STREAM_LENGTH

Grade = Literal[tuple(GRADES)]


def _stream(value: str | None) -> str | None:
    """A stream is trimmed; an empty one means "no stream"."""
    if value is None:
        return None
    value = value.strip()
    return value or None


class ClassListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    academic_year_id: uuid.UUID


class ClassTeacherOut(BaseModel):
    membership_id: uuid.UUID
    full_name: str
    # False once the person is no longer an active teacher of the school.
    # Their assignment is kept but no longer gives them the class.
    is_active: bool


class GradeOut(BaseModel):
    code: str
    name: str


class SchoolClassOut(BaseModel):
    id: uuid.UUID
    academic_year_id: uuid.UUID
    grade: str
    grade_name: str
    stream: str | None
    name: str
    teachers: list[ClassTeacherOut]
    # About the logged-in user (filled in by the class list only): whether
    # they are an active class teacher of it, and the subjects they teach it.
    is_class_teacher: bool = False
    my_subjects: list[str] = []


class CreateClassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    academic_year_id: uuid.UUID
    grade: Grade
    stream: str | None = Field(default=None, max_length=MAX_STREAM_LENGTH)

    _stream = field_validator("stream")(_stream)


class UpdateClassRequest(BaseModel):
    """Only the fields sent are changed. `"stream": null` (or "") removes it."""

    model_config = ConfigDict(extra="forbid")

    grade: Grade | None = None
    stream: str | None = Field(default=None, max_length=MAX_STREAM_LENGTH)

    @field_validator("grade", mode="before")
    @classmethod
    def _grade_not_null(cls, value):
        if value is None:
            raise ValueError("Must not be null.")
        return value

    _stream = field_validator("stream")(_stream)

    @model_validator(mode="after")
    def _check(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one of grade and stream.")
        return self


class AssignTeacherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: uuid.UUID
