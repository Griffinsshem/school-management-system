"""Student records in the current school.

Two independent layers keep schools apart here: every query filters on the
active school (`current_school()`), and PostgreSQL Row-Level Security limits
the API's database user to that school's rows even if a filter were missing.
A student ID from another school therefore gets the same 404 as an unknown one.
"""

import uuid

from flask import Blueprint, current_app, jsonify
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.auth.permissions import STUDENTS_MANAGE, STUDENTS_READ, permission_required
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import AcademicYear, Enrolment, Student
from app.schemas import parse_json_body, parse_query
from app.schemas.students import (
    CreateStudentRequest,
    StudentListQuery,
    StudentOut,
    UpdateStudentRequest,
)

students_bp = Blueprint("students", __name__, url_prefix="/school/students")

UNIQUE_VIOLATION = "23505"
ADMISSION_NUMBER_TAKEN = "Another student in this school has that admission number."
NOT_FOUND = "Student not found."


def _student_json(student: Student) -> dict:
    return StudentOut.model_validate(student).model_dump(mode="json")


def _like_pattern(text: str) -> str:
    """A LIKE pattern matching `text` anywhere, with % and _ taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _find(student_id: uuid.UUID) -> Student | None:
    return db.session.scalar(
        select(Student).where(Student.id == student_id, Student.school_id == current_school().id)
    )


def _find_for_change(student_id: uuid.UUID, action: str) -> Student:
    """The student to change, or a recorded refusal and 404."""
    school_id = current_school().id
    student = _find(student_id)
    if student is None:
        audit.record_denied(
            action, school_id=school_id, target_type="student", target_id=student_id
        )
        raise ApiError(404, "not_found", NOT_FOUND)
    return student


def _save(step) -> None:
    """Run `step` (flush or commit); a duplicate admission number becomes a 409.

    Other database errors are not disguised: they propagate as they are.
    """
    try:
        step()
    except IntegrityError as error:
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise ApiError(409, "admission_number_taken", ADMISSION_NUMBER_TAKEN) from None
        raise


@students_bp.get("")
@permission_required(STUDENTS_READ)
def list_students():
    query = parse_query(StudentListQuery)
    conditions = [Student.school_id == current_school().id]
    if query.q:
        pattern = _like_pattern(query.q)
        conditions.append(
            or_(
                Student.full_name.ilike(pattern, escape="\\"),
                Student.admission_number.ilike(pattern, escape="\\"),
            )
        )
    if query.not_enrolled_in:
        year = db.session.scalar(
            select(AcademicYear.id).where(
                AcademicYear.id == query.not_enrolled_in,
                AcademicYear.school_id == current_school().id,
            )
        )
        if year is None:
            raise ApiError(404, "not_found", "School year not found.")
        enrolled = select(Enrolment.student_id).where(Enrolment.academic_year_id == year)
        conditions += [Student.is_active.is_(True), Student.id.not_in(enrolled)]

    total = db.session.scalar(select(func.count()).select_from(Student).where(*conditions))
    students = db.session.scalars(
        select(Student)
        .where(*conditions)
        .order_by(Student.full_name, Student.admission_number, Student.id)
        .limit(query.per_page)
        .offset((query.page - 1) * query.per_page)
    )
    return jsonify(
        {
            "students": [_student_json(student) for student in students],
            "page": query.page,
            "per_page": query.per_page,
            "total": total,
        }
    )


@students_bp.post("")
@permission_required(STUDENTS_MANAGE)
def create_student():
    data = parse_json_body(CreateStudentRequest)
    school_id = current_school().id
    student = Student(
        school_id=school_id,
        admission_number=data.admission_number,
        full_name=data.full_name,
        date_of_birth=data.date_of_birth,
    )
    db.session.add(student)
    _save(db.session.flush)  # Assigns the ID and checks uniqueness.
    student_id = student.id
    audit.record(
        "student.created", school_id=school_id, target_type="student", target_id=student_id
    )
    _save(db.session.commit)

    current_app.logger.info("Student created: student_id=%s school_id=%s", student_id, school_id)
    return jsonify({"student": _student_json(student)}), 201


@students_bp.get("/<uuid:student_id>")
@permission_required(STUDENTS_READ)
def get_student(student_id: uuid.UUID):
    student = _find(student_id)
    if student is None:
        raise ApiError(404, "not_found", NOT_FOUND)
    return jsonify({"student": _student_json(student)})


@students_bp.patch("/<uuid:student_id>")
@permission_required(STUDENTS_MANAGE)
def update_student(student_id: uuid.UUID):
    data = parse_json_body(UpdateStudentRequest)
    student = _find_for_change(student_id, "student.updated")

    for field in data.model_fields_set:
        setattr(student, field, getattr(data, field))
    audit.record(
        "student.updated", school_id=student.school_id, target_type="student", target_id=student.id
    )
    _save(db.session.commit)

    current_app.logger.info("Student updated: student_id=%s", student_id)
    return jsonify({"student": _student_json(student)})


@students_bp.post("/<uuid:student_id>/deactivate")
@permission_required(STUDENTS_MANAGE)
def deactivate_student(student_id: uuid.UUID):
    student = _find_for_change(student_id, "student.deactivated")

    if student.is_active:
        student.is_active = False
        audit.record(
            "student.deactivated",
            school_id=student.school_id,
            target_type="student",
            target_id=student.id,
        )
        db.session.commit()
        current_app.logger.info("Student deactivated: student_id=%s", student_id)
    return jsonify({"student": _student_json(student)})
