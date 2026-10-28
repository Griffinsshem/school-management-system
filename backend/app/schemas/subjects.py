"""Schemas for subjects, class subjects and subject teachers (D3).

Names and codes are trimmed, and spaces inside them are collapsed to one
("Social  Studies" becomes "Social Studies"). A code is stored as written;
it is unique regardless of letter case. An empty code means "no code".
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.subject import MAX_SUBJECT_CODE_LENGTH, MAX_SUBJECT_NAME_LENGTH


def _squeeze(value: str) -> str:
    return " ".join(value.split())


def _name(value: str) -> str:
    value = _squeeze(value)
    if not value:
        raise ValueError("Must not be blank.")
    if len(value) > MAX_SUBJECT_NAME_LENGTH:
        raise ValueError(f"Must be at most {MAX_SUBJECT_NAME_LENGTH} characters.")
    return value


def _code(value: str | None) -> str | None:
    if value is None:
        return None
    value = _squeeze(value)
    if len(value) > MAX_SUBJECT_CODE_LENGTH:
        raise ValueError(f"Must be at most {MAX_SUBJECT_CODE_LENGTH} characters.")
    return value or None


# Room for stray spaces around a name or code; the validators check the rest.
_NAME_INPUT = MAX_SUBJECT_NAME_LENGTH + 40
_CODE_INPUT = MAX_SUBJECT_CODE_LENGTH + 40


class SubjectOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None
    is_active: bool


class CreateSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=_NAME_INPUT)
    code: str | None = Field(default=None, max_length=_CODE_INPUT)

    _check_name = field_validator("name")(_name)
    _check_code = field_validator("code")(_code)


class UpdateSubjectRequest(BaseModel):
    """Only the fields sent are changed. `"code": null` (or "") removes it."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_INPUT)
    code: str | None = Field(default=None, max_length=_CODE_INPUT)
    is_active: bool | None = None

    @field_validator("name", "is_active", mode="before")
    @classmethod
    def _not_null(cls, value):
        if value is None:
            raise ValueError("Must not be null.")
        return value

    _check_name = field_validator("name")(_name)
    _check_code = field_validator("code")(_code)

    @model_validator(mode="after")
    def _check(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one of name, code and is_active.")
        return self


class AddClassSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: uuid.UUID


class AssignSubjectTeacherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: uuid.UUID


class SubjectTeacherOut(BaseModel):
    membership_id: uuid.UUID
    full_name: str
    # False once the person is no longer an active teacher of the school.
    is_active: bool


class ClassSubjectOut(BaseModel):
    subject: SubjectOut
    teachers: list[SubjectTeacherOut]
