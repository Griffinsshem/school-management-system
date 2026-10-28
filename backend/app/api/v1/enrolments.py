"""The students of a class: enrolling, moving and removing them (C3).

- Staff with `classes.read` see every class list; a teacher (`classes.read_own`)
  sees only the lists of classes they are an active class teacher of, and
  only each student's name and admission number. Another class's list looks
  exactly like a missing one (404).
- School administrators and registrars (`enrolments.manage`) enrol, move and
  remove students. Only active students can be enrolled; a student is in at
  most one class per school year (also enforced by the database).

Every change is audited, one event per student.
"""

import uuid

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.auth.permissions import (
    CLASSES_READ,
    CLASSES_READ_OWN,
    ENROLMENTS_MANAGE,
    STUDENTS_READ,
    current_permissions,
    permission_required,
)
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import ClassTeacher, Enrolment, Membership, SchoolClass, Student
from app.models.school_class import TEACHER_ROLE
from app.schemas import parse_json_body
from app.schemas.enrolments import (
    ClassStudentOut,
    ClassStudentWithStatusOut,
    EnrolRequest,
    MoveRequest,
)

enrolments_bp = Blueprint("enrolments", __name__, url_prefix="/school/classes")

UNIQUE_VIOLATION = "23505"
CLASS_NOT_FOUND = "Class not found."
NOT_IN_CLASS = "That student is not in this class."
# Names listed in a refusal before "and N more".
MAX_NAMES_IN_MESSAGE = 5


def _invalid(message: str) -> ApiError:
    details = [{"field": "", "message": message}]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def _find_class(class_id: uuid.UUID) -> SchoolClass | None:
    return db.session.scalar(
        select(SchoolClass).where(
            SchoolClass.id == class_id, SchoolClass.school_id == current_school().id
        )
    )


def _teaches(school_class: SchoolClass) -> bool:
    """Whether the logged-in user is an active class teacher of this class."""
    return (
        db.session.scalar(
            select(ClassTeacher.id)
            .join(Membership, ClassTeacher.membership_id == Membership.id)
            .where(
                ClassTeacher.class_id == school_class.id,
                Membership.user_id == g.current_user.id,
                Membership.role == TEACHER_ROLE,
                Membership.is_active.is_(True),
            )
            .limit(1)
        )
        is not None
    )


def _class_for(class_id: uuid.UUID, action: str, *, reading: bool = False) -> SchoolClass:
    """The class, if this user may use it; otherwise a recorded refusal and 404."""
    school_class = _find_class(class_id)
    allowed = school_class is not None and (
        not reading or CLASSES_READ in current_permissions() or _teaches(school_class)
    )
    if not allowed:
        # Another school's class, or a class this teacher does not teach,
        # looks exactly like one that does not exist.
        audit.record_denied(
            action, school_id=current_school().id, target_type="class", target_id=class_id
        )
        raise ApiError(404, "not_found", CLASS_NOT_FOUND)
    return school_class


def _class_list(school_class: SchoolClass) -> dict:
    """The class and its students by name, with only what this user may see."""
    students = db.session.scalars(
        select(Student)
        .join(Enrolment, Enrolment.student_id == Student.id)
        .where(Enrolment.class_id == school_class.id)
        .order_by(Student.full_name, Student.admission_number, Student.id)
    )
    shape = ClassStudentWithStatusOut if STUDENTS_READ in current_permissions() else ClassStudentOut
    return {
        "class": {
            "id": str(school_class.id),
            "academic_year_id": str(school_class.academic_year_id),
            "name": school_class.name,
        },
        "students": [
            shape.model_validate(s, from_attributes=True).model_dump(mode="json") for s in students
        ],
    }


def _names(rows: list[tuple[str, str]]) -> str:
    """ "Amani Demo (ADM-1), Baraka Demo (ADM-2) and 3 more"."""
    shown = [f"{name} ({number})" for name, number in rows[:MAX_NAMES_IN_MESSAGE]]
    hidden = len(rows) - len(shown)
    return ", ".join(shown) + (f" and {hidden} more" if hidden else "")


def _find_enrolment(school_class: SchoolClass, student_id: uuid.UUID) -> Enrolment | None:
    return db.session.scalar(
        select(Enrolment).where(
            Enrolment.class_id == school_class.id, Enrolment.student_id == student_id
        )
    )


@enrolments_bp.get("/<uuid:class_id>/students")
@permission_required(CLASSES_READ, CLASSES_READ_OWN)
def class_students(class_id: uuid.UUID):
    school_class = _class_for(class_id, "class.students_read", reading=True)
    return jsonify(_class_list(school_class))


@enrolments_bp.post("/<uuid:class_id>/students")
@permission_required(ENROLMENTS_MANAGE)
def enrol(class_id: uuid.UUID):
    data = parse_json_body(EnrolRequest)
    school_id = current_school().id
    school_class = _class_for(class_id, "enrolment.added")
    wanted = set(data.student_ids)

    usable = set(
        db.session.scalars(
            select(Student.id).where(
                Student.id.in_(wanted),
                Student.school_id == school_id,
                Student.is_active.is_(True),
            )
        )
    )
    if usable != wanted:
        db.session.rollback()
        missing = len(wanted - usable)
        raise _invalid(
            f"{missing} of the chosen students cannot be enrolled: only active students "
            "of this school can be."
        )

    already = db.session.execute(
        select(Student.full_name, Student.admission_number, SchoolClass)
        .join(Enrolment, Enrolment.student_id == Student.id)
        .join(SchoolClass, Enrolment.class_id == SchoolClass.id)
        .where(
            Enrolment.academic_year_id == school_class.academic_year_id,
            Enrolment.student_id.in_(wanted),
        )
        .order_by(Student.full_name, Student.admission_number)
    ).all()
    if already:
        db.session.rollback()
        # Group by class so the message says where each student already is.
        by_class: dict[str, list[tuple[str, str]]] = {}
        for name, number, other in already:
            by_class.setdefault(other.name, []).append((name, number))
        where = "; ".join(f"{_names(rows)} in {name}" for name, rows in by_class.items())
        raise ApiError(
            409,
            "already_enrolled",
            f"Already in a class this school year: {where}. Move them instead.",
        )

    for student_id in sorted(wanted):
        db.session.add(
            Enrolment(
                school_id=school_id,
                academic_year_id=school_class.academic_year_id,
                class_id=school_class.id,
                student_id=student_id,
            )
        )
        audit.record(
            "enrolment.added", school_id=school_id, target_type="student", target_id=student_id
        )
    try:
        db.session.flush()
    except IntegrityError as error:
        # Someone enrolled one of them at the same moment.
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise ApiError(
                409,
                "already_enrolled",
                "Some of these students were enrolled by someone else just now. Reload "
                "and try again.",
            ) from None
        raise
    body = _class_list(school_class)
    db.session.commit()

    current_app.logger.info("Students enrolled: class_id=%s count=%s", school_class.id, len(wanted))
    return jsonify(body), 201


@enrolments_bp.patch("/<uuid:class_id>/students/<uuid:student_id>")
@permission_required(ENROLMENTS_MANAGE)
def move(class_id: uuid.UUID, student_id: uuid.UUID):
    data = parse_json_body(MoveRequest)
    school_id = current_school().id
    school_class = _class_for(class_id, "enrolment.moved")
    enrolment = _find_enrolment(school_class, student_id)
    if enrolment is None:
        db.session.rollback()
        raise ApiError(404, "not_found", NOT_IN_CLASS)

    target = _find_class(data.class_id)
    if target is None or target.academic_year_id != school_class.academic_year_id:
        db.session.rollback()
        raise _invalid("Choose another class of the same school year.")
    if target.id != school_class.id:
        enrolment.class_id = target.id
        audit.record(
            "enrolment.moved", school_id=school_id, target_type="student", target_id=student_id
        )
    db.session.flush()
    body = _class_list(school_class)  # The list being looked at, without the student.
    db.session.commit()

    current_app.logger.info(
        "Student moved: student_id=%s from_class_id=%s to_class_id=%s",
        student_id,
        school_class.id,
        target.id,
    )
    return jsonify(body)


@enrolments_bp.delete("/<uuid:class_id>/students/<uuid:student_id>")
@permission_required(ENROLMENTS_MANAGE)
def remove(class_id: uuid.UUID, student_id: uuid.UUID):
    school_id = current_school().id
    school_class = _class_for(class_id, "enrolment.removed")
    enrolment = _find_enrolment(school_class, student_id)
    if enrolment is None:
        db.session.rollback()
        raise ApiError(404, "not_found", NOT_IN_CLASS)

    db.session.delete(enrolment)
    audit.record(
        "enrolment.removed", school_id=school_id, target_type="student", target_id=student_id
    )
    db.session.flush()
    body = _class_list(school_class)
    db.session.commit()

    current_app.logger.info(
        "Student removed from class: student_id=%s class_id=%s", student_id, school_class.id
    )
    return jsonify(body)
