"""Schemas for school years and terms.

Rules that only need the request itself are checked here (dates in order,
terms inside the year and in order). Rules that need other rows (no
overlapping years; a changed term or year still fitting the saved ones) are
checked in app/api/v1/academic_years.py with the same messages.
"""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.academic_year import MAX_YEAR_DAYS, MAX_YEAR_NAME_LENGTH, TERM_NUMBERS

EARLIEST_DATE = date(2000, 1, 1)
LATEST_DATE = date(2100, 12, 31)


def _plausible(value: date | None) -> date | None:
    if value is not None and not EARLIEST_DATE <= value <= LATEST_DATE:
        raise ValueError("Must be between the years 2000 and 2100.")
    return value


def _not_blank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Must not be blank.")
    return value


def year_problem(starts_on: date, ends_on: date) -> str | None:
    """Why these dates cannot make a school year, or None if they can."""
    if starts_on >= ends_on:
        return "The school year must end after it starts."
    if (ends_on - starts_on).days > MAX_YEAR_DAYS:
        return f"A school year can last at most {MAX_YEAR_DAYS} days."
    return None


def terms_problems(
    year_starts_on: date, year_ends_on: date, terms: list[tuple[int, date, date]]
) -> list[tuple[int, str]]:
    """Every (term number, message) for terms that do not fit the year.

    `terms` holds (number, starts_on, ends_on). Terms must each end after they
    start, lie inside the year, and follow each other in number order without
    overlapping (a term may start the day after the previous one ends).
    """
    problems = []
    ordered = sorted(terms)
    for number, starts_on, ends_on in ordered:
        if starts_on >= ends_on:
            problems.append((number, f"Term {number} must end after it starts."))
        elif starts_on < year_starts_on or ends_on > year_ends_on:
            problems.append((number, f"Term {number} must be inside the school year."))
    for (before, _, before_ends), (after, after_starts, _) in zip(
        ordered, ordered[1:], strict=False
    ):
        if after_starts <= before_ends:
            problems.append((after, f"Term {after} must start after Term {before} ends."))
    return problems


class TermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    name: str
    starts_on: date
    ends_on: date


class AcademicYearOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    starts_on: date
    ends_on: date
    terms: list[TermOut]


class TermDates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_on: date
    ends_on: date

    _plausible = field_validator("starts_on", "ends_on")(_plausible)


class NewTerm(TermDates):
    number: int = Field(ge=TERM_NUMBERS[0], le=TERM_NUMBERS[-1])


class CreateAcademicYearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_YEAR_NAME_LENGTH)
    starts_on: date
    ends_on: date
    terms: list[NewTerm] = Field(default_factory=list, max_length=len(TERM_NUMBERS))

    _trim = field_validator("name")(_not_blank)
    _plausible = field_validator("starts_on", "ends_on")(_plausible)

    @model_validator(mode="after")
    def _check_dates(self):
        problem = year_problem(self.starts_on, self.ends_on)
        if problem:
            raise ValueError(problem)
        numbers = [term.number for term in self.terms]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Each term number may appear only once.")
        problems = terms_problems(
            self.starts_on,
            self.ends_on,
            [(term.number, term.starts_on, term.ends_on) for term in self.terms],
        )
        if problems:
            raise ValueError(" ".join(message for _, message in problems))
        return self


class UpdateAcademicYearRequest(BaseModel):
    """Only the fields sent are changed. None of them may be null."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_YEAR_NAME_LENGTH)
    starts_on: date | None = None
    ends_on: date | None = None

    @field_validator("name", "starts_on", "ends_on", mode="before")
    @classmethod
    def _not_null(cls, value):
        if value is None:
            raise ValueError("Must not be null.")
        return value

    _trim = field_validator("name")(_not_blank)
    _plausible = field_validator("starts_on", "ends_on")(_plausible)

    @model_validator(mode="after")
    def _something_to_change(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one of name, starts_on and ends_on.")
        return self
