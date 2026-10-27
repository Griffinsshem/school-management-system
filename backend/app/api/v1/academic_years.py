"""School years and their terms in the current school (C1).

Every staff role may read them; only school administrators change them.
Years and terms are never deleted: mistakes are corrected by editing.

Rules that compare rows (years must not overlap; terms must fit inside their
year, in order) are checked while the school's row is locked, so two
administrators saving at the same moment cannot both pass the checks.

"Today" means today in Kenya, so the current term changes at midnight in
Nairobi rather than at midnight UTC (3 a.m. in Nairobi).
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.auth.permissions import ACADEMICS_MANAGE, ACADEMICS_READ, permission_required
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import AcademicYear, School, Term
from app.models.academic_year import TERM_NUMBERS
from app.schemas import parse_json_body
from app.schemas.academic_years import (
    AcademicYearOut,
    CreateAcademicYearRequest,
    TermDates,
    UpdateAcademicYearRequest,
    terms_problems,
    year_problem,
)

academic_years_bp = Blueprint("academic_years", __name__, url_prefix="/school/academic-years")

SCHOOL_TIME_ZONE = ZoneInfo("Africa/Nairobi")
UNIQUE_VIOLATION = "23505"
NOT_FOUND = "School year not found."
NAME_TAKEN = "This school already has a school year with that name."


def school_today() -> date:
    """Today's date in Kenya. Tests replace this to fix the date."""
    return datetime.now(SCHOOL_TIME_ZONE).date()


def _year_json(year: AcademicYear) -> dict:
    data = AcademicYearOut.model_validate(year).model_dump(mode="json")
    data["terms"].sort(key=lambda term: term["number"])  # Also for terms added just now.
    return data


def _invalid(*messages: str) -> ApiError:
    details = [{"field": "", "message": message} for message in messages]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def _lock_school(school_id: uuid.UUID) -> None:
    # Changes to one school's years and terms then run one at a time.
    db.session.execute(select(School.id).where(School.id == school_id).with_for_update())


def _years(school_id: uuid.UUID) -> list[AcademicYear]:
    return list(
        db.session.scalars(
            select(AcademicYear)
            .where(AcademicYear.school_id == school_id)
            .order_by(AcademicYear.starts_on.desc())
        )
    )


def _find_for_change(year_id: uuid.UUID, action: str) -> AcademicYear:
    """The year to change, or a recorded refusal and 404."""
    school_id = current_school().id
    year = db.session.scalar(
        select(AcademicYear).where(AcademicYear.id == year_id, AcademicYear.school_id == school_id)
    )
    if year is None:
        # Another school's year looks exactly like one that does not exist.
        audit.record_denied(
            action, school_id=school_id, target_type="academic_year", target_id=year_id
        )
        raise ApiError(404, "not_found", NOT_FOUND)
    return year


def _refuse_overlap(
    school_id: uuid.UUID, starts_on: date, ends_on: date, except_id: uuid.UUID | None = None
) -> None:
    """409 if another year of this school shares any day with these dates."""
    conditions = [
        AcademicYear.school_id == school_id,
        AcademicYear.starts_on <= ends_on,
        AcademicYear.ends_on >= starts_on,
    ]
    if except_id is not None:
        conditions.append(AcademicYear.id != except_id)
    other = db.session.scalar(select(AcademicYear).where(*conditions).limit(1))
    if other is not None:
        db.session.rollback()
        raise ApiError(
            409, "overlapping_year", f"These dates overlap the school year {other.name}."
        )


def _commit() -> None:
    """Commit; a duplicate year name becomes a 409. Other errors propagate."""
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise ApiError(409, "year_name_taken", NAME_TAKEN) from None
        raise


def _current(years: list[AcademicYear], today: date) -> dict:
    """Which year and term contain `today`, and the next term if not in one."""
    year = next((y for y in years if y.starts_on <= today <= y.ends_on), None)
    term = None
    if year is not None:
        term = next((t for t in year.terms if t.starts_on <= today <= t.ends_on), None)
    upcoming = sorted(
        (t for y in years for t in y.terms if t.starts_on > today), key=lambda t: t.starts_on
    )
    next_term = upcoming[0] if term is None and upcoming else None
    return {
        "today": today.isoformat(),
        "academic_year_id": str(year.id) if year else None,
        "term_number": term.number if term else None,
        "next_term": (
            {
                "academic_year_id": str(next_term.academic_year_id),
                "number": next_term.number,
                "starts_on": next_term.starts_on.isoformat(),
            }
            if next_term
            else None
        ),
    }


@academic_years_bp.get("")
@permission_required(ACADEMICS_READ)
def list_years():
    years = _years(current_school().id)
    return jsonify(
        {
            "academic_years": [_year_json(year) for year in years],
            "current": _current(years, school_today()),
        }
    )


@academic_years_bp.post("")
@permission_required(ACADEMICS_MANAGE)
def create_year():
    data = parse_json_body(CreateAcademicYearRequest)
    school_id = current_school().id
    _lock_school(school_id)
    _refuse_overlap(school_id, data.starts_on, data.ends_on)

    year = AcademicYear(
        school_id=school_id, name=data.name, starts_on=data.starts_on, ends_on=data.ends_on
    )
    for term in sorted(data.terms, key=lambda t: t.number):
        year.terms.append(
            Term(
                school_id=school_id,
                number=term.number,
                starts_on=term.starts_on,
                ends_on=term.ends_on,
            )
        )
    db.session.add(year)
    try:
        db.session.flush()  # Assigns IDs for the audit events.
    except IntegrityError as error:
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise ApiError(409, "year_name_taken", NAME_TAKEN) from None
        raise
    year_id = year.id
    audit.record(
        "academic_year.created", school_id=school_id, target_type="academic_year", target_id=year_id
    )
    for term in year.terms:
        audit.record("term.saved", school_id=school_id, target_type="term", target_id=term.id)
    _commit()

    current_app.logger.info(
        "School year created: academic_year_id=%s school_id=%s", year_id, school_id
    )
    return jsonify({"academic_year": _year_json(year)}), 201


@academic_years_bp.patch("/<uuid:year_id>")
@permission_required(ACADEMICS_MANAGE)
def update_year(year_id: uuid.UUID):
    data = parse_json_body(UpdateAcademicYearRequest)
    school_id = current_school().id
    _lock_school(school_id)
    year = _find_for_change(year_id, "academic_year.updated")

    starts_on = data.starts_on if "starts_on" in data.model_fields_set else year.starts_on
    ends_on = data.ends_on if "ends_on" in data.model_fields_set else year.ends_on
    problem = year_problem(starts_on, ends_on)
    if problem:
        db.session.rollback()
        raise _invalid(problem)
    problems = terms_problems(
        starts_on, ends_on, [(t.number, t.starts_on, t.ends_on) for t in year.terms]
    )
    if problems:
        db.session.rollback()
        raise _invalid(*(message for _, message in problems))
    _refuse_overlap(school_id, starts_on, ends_on, except_id=year.id)

    for field in data.model_fields_set:
        setattr(year, field, getattr(data, field))
    audit.record(
        "academic_year.updated", school_id=school_id, target_type="academic_year", target_id=year.id
    )
    _commit()

    current_app.logger.info("School year updated: academic_year_id=%s", year_id)
    return jsonify({"academic_year": _year_json(year)})


@academic_years_bp.put("/<uuid:year_id>/terms/<int:number>")
@permission_required(ACADEMICS_MANAGE)
def save_term(year_id: uuid.UUID, number: int):
    if number not in TERM_NUMBERS:
        raise ApiError(404, "not_found", "A school year has terms 1, 2 and 3 only.")
    data = parse_json_body(TermDates)
    school_id = current_school().id
    _lock_school(school_id)
    year = _find_for_change(year_id, "term.saved")

    others = [(t.number, t.starts_on, t.ends_on) for t in year.terms if t.number != number]
    problems = terms_problems(
        year.starts_on, year.ends_on, [*others, (number, data.starts_on, data.ends_on)]
    )
    if problems:
        db.session.rollback()
        raise _invalid(*(message for _, message in problems))

    term = next((t for t in year.terms if t.number == number), None)
    if term is None:
        term = Term(school_id=school_id, number=number)
        year.terms.append(term)
    term.starts_on = data.starts_on
    term.ends_on = data.ends_on
    db.session.flush()  # Assigns a new term's ID for the audit event.
    audit.record("term.saved", school_id=school_id, target_type="term", target_id=term.id)
    _commit()

    current_app.logger.info("Term saved: academic_year_id=%s number=%s", year_id, number)
    return jsonify({"academic_year": _year_json(year)})
