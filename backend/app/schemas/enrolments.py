"""Schemas for enrolments: the students of a class (C3)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_ENROL_AT_ONCE = 100


class ClassStudentOut(BaseModel):
    """A student in a class list.

    Teachers get only these three fields: their class list needs nothing
    more (the decision of 2026-10-26), and the API itself leaves the rest out.
    """

    id: uuid.UUID
    admission_number: str
    full_name: str


class ClassStudentWithStatusOut(ClassStudentOut):
    """For staff who may read student records: also whether the record is active."""

    is_active: bool


class EnrolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_ENROL_AT_ONCE)

    @field_validator("student_ids")
    @classmethod
    def _no_repeats(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Each student may appear only once.")
        return value


class MoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_id: uuid.UUID
