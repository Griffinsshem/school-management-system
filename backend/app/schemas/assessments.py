"""Schemas for assessments and marks (D4).

A score is sent as a JSON number with at most one decimal place (12 or
12.5). Whether it fits the assessment's maximum, and whether the date is
inside the term, depend on stored data, so app/api/v1/assessments.py checks
those.
"""

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.models.assessment import MAX_ASSESSMENT_NAME_LENGTH, MAX_SCORE_LIMIT, MAX_WEIGHT

# The largest mark sheet that can be saved at once (far above any real class).
MAX_MARKS_PER_SHEET = 200
SCORE_MESSAGE = "A score is a number from 0 with at most one decimal place, such as 12 or 12.5."


def _name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("Must not be blank.")
    if len(value) > MAX_ASSESSMENT_NAME_LENGTH:
        raise ValueError(f"Must be at most {MAX_ASSESSMENT_NAME_LENGTH} characters.")
    return value


_NAME_INPUT = MAX_ASSESSMENT_NAME_LENGTH + 40


class TermQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: int | None = Field(default=None, ge=1, le=3)


class RequiredTermQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: int = Field(ge=1, le=3)


class CreateAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: int = Field(ge=1, le=3)
    name: str = Field(min_length=1, max_length=_NAME_INPUT)
    max_score: int = Field(ge=1, le=MAX_SCORE_LIMIT)
    held_on: dt.date
    # A whole percentage of the subject's term result (D6), or none; a JSON
    # whole number only ("30" or 30.5 is refused).
    weight: StrictInt | None = Field(default=None, ge=1, le=MAX_WEIGHT)

    _check_name = field_validator("name")(_name)


class UpdateAssessmentRequest(BaseModel):
    """Only the fields sent are changed. The term cannot change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_INPUT)
    max_score: int | None = Field(default=None, ge=1, le=MAX_SCORE_LIMIT)
    held_on: dt.date | None = None
    # `"weight": null` removes it.
    weight: StrictInt | None = Field(default=None, ge=1, le=MAX_WEIGHT)

    @field_validator("name", "max_score", "held_on", mode="before")
    @classmethod
    def _not_null(cls, value):
        if value is None:
            raise ValueError("Must not be null.")
        return value

    _check_name = field_validator("name")(_name)

    @model_validator(mode="after")
    def _check(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one of name, max_score, held_on and weight.")
        return self


class MarkIn(BaseModel):
    """One student's mark: a score, "did not sit", or neither (clears it)."""

    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID
    score: Decimal | None = None
    did_not_sit: bool = False

    @field_validator("score", mode="before")
    @classmethod
    def _number(cls, value):
        # A JSON number only: "12" as text, true or NaN are refused.
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(SCORE_MESSAGE)
        return Decimal(str(value))

    @field_validator("score")
    @classmethod
    def _one_decimal_place(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite() or value < 0 or value != value.quantize(Decimal("0.1")):
            raise ValueError(SCORE_MESSAGE)
        return value.quantize(Decimal("0.1"))

    @model_validator(mode="after")
    def _score_or_did_not_sit(self):
        if self.did_not_sit and self.score is not None:
            raise ValueError("A student who did not sit cannot also have a score.")
        return self


class SaveMarksRequest(BaseModel):
    """Marks to save. Students not listed keep their marks."""

    model_config = ConfigDict(extra="forbid")

    marks: list[MarkIn] = Field(min_length=1, max_length=MAX_MARKS_PER_SHEET)

    @field_validator("marks")
    @classmethod
    def _one_mark_per_student(cls, value: list[MarkIn]) -> list[MarkIn]:
        ids = [mark.student_id for mark in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Each student may appear only once.")
        return value
