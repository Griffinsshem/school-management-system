"""Daily attendance registers (D1).

Who may do what:
- School administrators (`attendance.record`) take and correct any class's
  register for any school day up to today.
- Teachers (`attendance.record_own`) take and correct the registers of the
  classes they are an active class teacher of, for today and the previous
  TEACHER_DAYS_BACK days. Older registers are changed by an administrator.
- Administrators and principals (`attendance.read`) read every register,
  each class's term summary and the school's overview of a day. Teachers
  read their own classes' registers and summaries. Another class looks
  exactly like a missing one (404).

Rules for the day: it must be inside a term of the class's school year and
not in the future ("today" is today in Kenya). Weekends are allowed, for
Saturday classes and events.

A register is saved whole: one mark for every student in it, all or none.
A new register covers the class's active students at that moment; a
correction covers exactly the students already in it, so history does not
change when students later move or leave (decision of 2026-10-27). Nothing
is deleted. Taking a register is one audit event; a correction is one event
for the register and one for each student whose mark changed.
"""

import uuid
from datetime import date, timedelta

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app import audit
from app.api.v1 import academic_years as years_api
from app.api.v1.enrolments import _teaches  # The same "teaches this class" rule as C3.
from app.auth.permissions import (
    ATTENDANCE_READ,
    ATTENDANCE_RECORD,
    ATTENDANCE_RECORD_OWN,
    current_permissions,
    permission_required,
)
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import (
    AcademicYear,
    AttendanceMark,
    AttendanceRegister,
    Enrolment,
    SchoolClass,
    Student,
    Term,
    User,
)
from app.models.attendance import REASONS, STATUSES
from app.models.school_class import GRADES
from app.schemas import parse_json_body, parse_query
from app.schemas.attendance import OverviewQuery, SaveRegisterRequest, TermSummaryQuery

attendance_bp = Blueprint("attendance", __name__, url_prefix="/school")

TEACHER_DAYS_BACK = 7
UNIQUE_VIOLATION = "23505"
CLASS_NOT_FOUND = "Class not found."
GRADE_ORDER = {grade: index for index, grade in enumerate(GRADES)}


def _invalid(message: str) -> ApiError:
    details = [{"field": "", "message": message}]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def _parse_day(text: str) -> date:
    """A date written YYYY-MM-DD, as in the URL."""
    try:
        if len(text) != len("2027-02-01"):
            raise ValueError
        return date.fromisoformat(text)
    except ValueError:
        raise _invalid("The date must be a real date written YYYY-MM-DD.") from None


def _records_all() -> bool:
    return ATTENDANCE_RECORD in current_permissions()


def _class_for(class_id: uuid.UUID, action: str, *, writing: bool) -> SchoolClass:
    """The class, if this user may read (or change) its registers; otherwise a
    recorded refusal and 404."""
    permissions = current_permissions()
    school_class = db.session.scalar(
        select(SchoolClass).where(
            SchoolClass.id == class_id, SchoolClass.school_id == current_school().id
        )
    )
    every_class = ATTENDANCE_RECORD if writing else ATTENDANCE_READ
    allowed = school_class is not None and (
        every_class in permissions
        or (ATTENDANCE_RECORD_OWN in permissions and _teaches(school_class))
    )
    if not allowed:
        audit.record_denied(
            action, school_id=current_school().id, target_type="class", target_id=class_id
        )
        raise ApiError(404, "not_found", CLASS_NOT_FOUND)
    return school_class


def _term_on(academic_year_id: uuid.UUID, day: date) -> Term | None:
    return db.session.scalar(
        select(Term).where(
            Term.academic_year_id == academic_year_id,
            Term.starts_on <= day,
            Term.ends_on >= day,
        )
    )


def _day_problem(school_class: SchoolClass, day: date, today: date) -> str | None:
    """Why no register can be taken for this class on this day, if any."""
    if day > today:
        return "Attendance cannot be taken for a day that has not happened yet."
    if _term_on(school_class.academic_year_id, day) is None:
        year = db.session.get(AcademicYear, school_class.academic_year_id)
        return f"{day.isoformat()} is not inside a term of the school year {year.name}."
    return None


def _earliest_for_teachers(today: date) -> date:
    return today - timedelta(days=TEACHER_DAYS_BACK)


def _find_register(school_class: SchoolClass, day: date, *, lock: bool = False):
    query = select(AttendanceRegister).where(
        AttendanceRegister.class_id == school_class.id, AttendanceRegister.date == day
    )
    if lock:
        query = query.with_for_update()
    return db.session.scalar(query)


def _class_json(school_class: SchoolClass) -> dict:
    return {
        "id": str(school_class.id),
        "academic_year_id": str(school_class.academic_year_id),
        "name": school_class.name,
    }


def _student_json(student: Student) -> dict:
    # Only what a class teacher needs (as in the class list).
    return {
        "id": str(student.id),
        "admission_number": student.admission_number,
        "full_name": student.full_name,
    }


def _class_students(school_class: SchoolClass) -> list[Student]:
    """The class's active students: who a new register is for."""
    return list(
        db.session.scalars(
            select(Student)
            .join(Enrolment, Enrolment.student_id == Student.id)
            .where(Enrolment.class_id == school_class.id, Student.is_active.is_(True))
            .order_by(Student.full_name, Student.admission_number, Student.id)
        )
    )


def _register_json(school_class: SchoolClass, day: date, register, today: date) -> dict:
    term = _term_on(school_class.academic_year_id, day)
    usable = _day_problem(school_class, day, today) is None
    window_ends_on = None
    if _records_all():
        editable = usable
    else:  # A teacher of this class, or someone who may only read.
        may_record = ATTENDANCE_RECORD_OWN in current_permissions() and _teaches(school_class)
        editable = may_record and usable and day >= _earliest_for_teachers(today)
        if may_record:
            window_ends_on = (day + timedelta(days=TEACHER_DAYS_BACK)).isoformat()

    body = {
        "class": _class_json(school_class),
        "date": day.isoformat(),
        "term_number": term.number if term else None,
        "taken": register is not None,
        "taken_by": None,
        "taken_at": None,
        "updated_by": None,
        "updated_at": None,
        "editable": editable,
        "teacher_can_change_until": window_ends_on,
    }
    if register is None:
        body["marks"] = [
            {"student": _student_json(s), "status": "present", "reason": None}
            for s in _class_students(school_class)
        ]
        return body

    taken_by, updated_by = aliased(User), aliased(User)
    names = db.session.execute(
        select(taken_by.full_name, updated_by.full_name)
        .select_from(AttendanceRegister)
        .join(taken_by, AttendanceRegister.taken_by_user_id == taken_by.id)
        .join(updated_by, AttendanceRegister.updated_by_user_id == updated_by.id)
        .where(AttendanceRegister.id == register.id)
    ).one()
    rows = db.session.execute(
        select(AttendanceMark, Student)
        .join(Student, AttendanceMark.student_id == Student.id)
        .where(AttendanceMark.register_id == register.id)
        .order_by(Student.full_name, Student.admission_number, Student.id)
    )
    body.update(
        taken_by=names[0],
        taken_at=register.created_at.isoformat(),
        updated_by=names[1],
        updated_at=register.updated_at.isoformat(),
        marks=[
            {"student": _student_json(student), "status": mark.status, "reason": mark.reason}
            for mark, student in rows
        ],
    )
    return body


@attendance_bp.get("/classes/<uuid:class_id>/attendance/<day_text>")
@permission_required(ATTENDANCE_READ, ATTENDANCE_RECORD_OWN)
def read_register(class_id: uuid.UUID, day_text: str):
    day = _parse_day(day_text)
    school_class = _class_for(class_id, "attendance.read", writing=False)
    today = years_api.school_today()
    register = _find_register(school_class, day)
    if register is None:
        # Not taken: only days a register could be taken for have a blank one.
        problem = _day_problem(school_class, day, today)
        if problem:
            raise _invalid(problem)
    return jsonify(_register_json(school_class, day, register, today))


@attendance_bp.put("/classes/<uuid:class_id>/attendance/<day_text>")
@permission_required(ATTENDANCE_RECORD, ATTENDANCE_RECORD_OWN)
def save_register(class_id: uuid.UUID, day_text: str):
    day = _parse_day(day_text)
    data = parse_json_body(SaveRegisterRequest)
    school_id = current_school().id
    school_class = _class_for(class_id, "attendance.saved", writing=True)
    today = years_api.school_today()

    problem = _day_problem(school_class, day, today)
    if problem:
        db.session.rollback()
        raise _invalid(problem)
    if not _records_all() and day < _earliest_for_teachers(today):
        audit.record_denied(
            "attendance.saved", school_id=school_id, target_type="class", target_id=class_id
        )
        raise ApiError(
            403,
            "too_late_to_change",
            f"Teachers can take and correct registers for today and the previous "
            f"{TEACHER_DAYS_BACK} days. Ask a school administrator to change older ones.",
        )

    sent = {mark.student_id: mark for mark in data.marks}
    register = _find_register(school_class, day, lock=True)
    user_id = g.current_user.id

    if register is None:
        expected = {student.id for student in _class_students(school_class)}
        if set(sent) != expected:
            db.session.rollback()
            raise ApiError(
                409,
                "class_list_changed",
                "The class list has changed since this register was opened. Reload it and "
                "try again.",
            )
        register = AttendanceRegister(
            school_id=school_id,
            academic_year_id=school_class.academic_year_id,
            class_id=school_class.id,
            date=day,
            taken_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        db.session.add(register)
        try:
            db.session.flush()
        except IntegrityError as error:
            db.session.rollback()
            if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                raise ApiError(
                    409,
                    "register_already_taken",
                    "Someone else saved this register just now. Reload it to see their marks.",
                ) from None
            raise
        for student_id, mark in sent.items():
            db.session.add(
                AttendanceMark(
                    school_id=school_id,
                    register_id=register.id,
                    student_id=student_id,
                    status=mark.status,
                    reason=mark.reason,
                )
            )
        audit.record(
            "attendance.taken",
            school_id=school_id,
            target_type="attendance_register",
            target_id=register.id,
        )
        created, changed = True, len(sent)
    else:
        existing = {
            mark.student_id: mark
            for mark in db.session.scalars(
                select(AttendanceMark).where(AttendanceMark.register_id == register.id)
            )
        }
        if set(sent) != set(existing):
            db.session.rollback()
            raise ApiError(
                409,
                "register_students_differ",
                "A correction must keep the students this register was taken for. Reload it "
                "and try again.",
            )
        changed = 0
        for student_id, mark in sent.items():
            old = existing[student_id]
            if (old.status, old.reason) != (mark.status, mark.reason):
                old.status, old.reason = mark.status, mark.reason
                changed += 1
                audit.record(
                    "attendance.mark_changed",
                    school_id=school_id,
                    target_type="student",
                    target_id=student_id,
                )
        if changed:
            register.updated_by_user_id = user_id
            register.updated_at = func.now()
            audit.record(
                "attendance.corrected",
                school_id=school_id,
                target_type="attendance_register",
                target_id=register.id,
            )
        created = False

    db.session.flush()
    db.session.refresh(register)  # The times the database just set.
    body = _register_json(school_class, day, register, today)
    db.session.commit()

    current_app.logger.info(
        "Attendance saved: class_id=%s date=%s created=%s marks_changed=%s",
        school_class.id,
        day.isoformat(),
        created,
        changed,
    )
    return jsonify(body), 201 if created else 200


def _empty_counts() -> dict:
    return {**dict.fromkeys(STATUSES, 0), **dict.fromkeys(REASONS, 0)}


def _counts(rows) -> dict:
    """{key: {"present": n, "absent": n, "late": n, "sick": n, ...}} from
    (key, status, reason, count) rows."""
    result: dict = {}
    for key, status, reason, count in rows:
        entry = result.setdefault(key, _empty_counts())
        entry[status] += count
        if reason:
            entry[reason] += count
    return result


def _split(entry: dict) -> dict:
    return {
        **{status: entry[status] for status in STATUSES},
        "absent_by_reason": {reason: entry[reason] for reason in REASONS},
    }


@attendance_bp.get("/classes/<uuid:class_id>/attendance")
@permission_required(ATTENDANCE_READ, ATTENDANCE_RECORD_OWN)
def term_summary(class_id: uuid.UUID):
    query = parse_query(TermSummaryQuery)
    school_class = _class_for(class_id, "attendance.read", writing=False)
    term = db.session.scalar(
        select(Term).where(
            Term.academic_year_id == school_class.academic_year_id, Term.number == query.term
        )
    )
    if term is None:
        raise ApiError(404, "not_found", f"This school year has no Term {query.term}.")

    in_term = (
        AttendanceRegister.class_id == school_class.id,
        AttendanceRegister.date >= term.starts_on,
        AttendanceRegister.date <= term.ends_on,
    )
    marks = (
        select(AttendanceMark)
        .join(AttendanceRegister, AttendanceMark.register_id == AttendanceRegister.id)
        .where(*in_term)
        .subquery()
    )
    by_day = _counts(
        db.session.execute(
            select(AttendanceRegister.date, marks.c.status, marks.c.reason, func.count())
            .join(marks, marks.c.register_id == AttendanceRegister.id)
            .group_by(AttendanceRegister.date, marks.c.status, marks.c.reason)
        )
    )
    days = list(
        db.session.scalars(
            select(AttendanceRegister.date).where(*in_term).order_by(AttendanceRegister.date)
        )
    )
    by_student = _counts(
        db.session.execute(
            select(marks.c.student_id, marks.c.status, marks.c.reason, func.count()).group_by(
                marks.c.student_id, marks.c.status, marks.c.reason
            )
        )
    )
    in_class = {student.id: student for student in _class_students(school_class)}
    students = {**in_class}
    if by_student:
        students.update(
            (student.id, student)
            for student in db.session.scalars(select(Student).where(Student.id.in_(by_student)))
        )
    ordered = sorted(students.values(), key=lambda s: (s.full_name, s.admission_number, s.id))

    return jsonify(
        {
            "class": _class_json(school_class),
            "term": {
                "number": term.number,
                "starts_on": term.starts_on.isoformat(),
                "ends_on": term.ends_on.isoformat(),
            },
            "registers": [
                {"date": day.isoformat(), **_split(by_day.get(day, _empty_counts()))}
                for day in days
            ],
            "students": [
                {
                    "student": _student_json(student),
                    "in_class": student.id in in_class,
                    **_split(by_student.get(student.id, _empty_counts())),
                }
                for student in ordered
            ],
        }
    )


@attendance_bp.get("/attendance")
@permission_required(ATTENDANCE_READ)
def school_overview():
    query = parse_query(OverviewQuery)
    school_id = current_school().id
    today = years_api.school_today()
    day = query.date or today
    if day > today:
        raise _invalid("Attendance cannot be taken for a day that has not happened yet.")

    year = db.session.scalar(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.starts_on <= day,
            AcademicYear.ends_on >= day,
        )
    )
    body = {"date": day.isoformat(), "academic_year_id": None, "term_number": None, "classes": []}
    if year is None:
        return jsonify(body)
    term = _term_on(year.id, day)
    body.update(academic_year_id=str(year.id), term_number=term.number if term else None)

    classes = sorted(
        db.session.scalars(select(SchoolClass).where(SchoolClass.academic_year_id == year.id)),
        key=lambda c: (GRADE_ORDER.get(c.grade, len(GRADE_ORDER)), c.stream or ""),
    )
    registers = {
        register.class_id: register
        for register in db.session.scalars(
            select(AttendanceRegister).where(
                AttendanceRegister.academic_year_id == year.id, AttendanceRegister.date == day
            )
        )
    }
    counts = _counts(
        db.session.execute(
            select(AttendanceRegister.class_id, AttendanceMark.status, AttendanceMark.reason,
                   func.count())
            .join(AttendanceMark, AttendanceMark.register_id == AttendanceRegister.id)
            .where(AttendanceRegister.academic_year_id == year.id, AttendanceRegister.date == day)
            .group_by(AttendanceRegister.class_id, AttendanceMark.status, AttendanceMark.reason)
        )
    )  # fmt: skip
    body["classes"] = [
        {
            "class": _class_json(school_class),
            "taken": school_class.id in registers,
            # All zero when not taken.
            **_split(counts.get(school_class.id, _empty_counts())),
        }
        for school_class in classes
    ]
    return jsonify(body)
