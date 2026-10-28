"""Classes in a school year and their class teachers (C2).

School administrators, principals and registrars see every class; a teacher
sees only the classes they are an active class teacher of or teach a subject
to (D3), with which of the two they are. Only school
administrators create and change classes and assign teachers.

Classes are never deleted: mistakes are corrected by editing. Removing a
class teacher deletes only that assignment.

Which grades exist depends on the year (Kenya's move from 8-4-4 to CBC; see
app/models/school_class.py). The database cannot check that rule, because it
needs the year's dates, so it is checked here.
"""

import uuid

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.auth.permissions import (
    CLASSES_MANAGE,
    CLASSES_READ,
    CLASSES_READ_OWN,
    current_permissions,
    permission_required,
)
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import (
    AcademicYear,
    ClassSubject,
    ClassTeacher,
    Membership,
    SchoolClass,
    Subject,
    SubjectTeacher,
    User,
)
from app.models.school_class import (
    FIRST_CBC_YEAR_OFFSET,
    GRADES,
    LAST_FORM_YEAR_OFFSET,
    TEACHER_ROLE,
    grade_exists_in,
    grades_in,
)
from app.schemas import parse_json_body, parse_query
from app.schemas.classes import (
    AssignTeacherRequest,
    ClassListQuery,
    ClassTeacherOut,
    CreateClassRequest,
    GradeOut,
    SchoolClassOut,
    UpdateClassRequest,
)

classes_bp = Blueprint("classes", __name__, url_prefix="/school/classes")

UNIQUE_VIOLATION = "23505"
YEAR_NOT_FOUND = "School year not found."
CLASS_NOT_FOUND = "Class not found."
GRADE_ORDER = {grade: index for index, grade in enumerate(GRADES)}


def _invalid(message: str) -> ApiError:
    details = [{"field": "", "message": message}]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def _grade_problem(grade: str, year: AcademicYear) -> str | None:
    """Why this grade cannot be a class in this school year, or None."""
    calendar_year = year.starts_on.year
    if grade_exists_in(grade, calendar_year):
        return None
    label = GRADES[grade]
    number = int(grade.rpartition("_")[2])
    if grade.startswith("form_"):
        last = LAST_FORM_YEAR_OFFSET + number
        return f"There is no {label} in {calendar_year}: the last {label} class was in {last}."
    first = FIRST_CBC_YEAR_OFFSET + number
    return f"There is no {label} in {calendar_year}: the first {label} class is in {first}."


def _find_year(year_id: uuid.UUID) -> AcademicYear | None:
    return db.session.scalar(
        select(AcademicYear).where(
            AcademicYear.id == year_id, AcademicYear.school_id == current_school().id
        )
    )


def _find_class_for_change(class_id: uuid.UUID, action: str) -> SchoolClass:
    """The class to change, or a recorded refusal and 404."""
    school_id = current_school().id
    school_class = db.session.scalar(
        select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.school_id == school_id)
    )
    if school_class is None:
        # Another school's class looks exactly like one that does not exist.
        audit.record_denied(action, school_id=school_id, target_type="class", target_id=class_id)
        raise ApiError(404, "not_found", CLASS_NOT_FOUND)
    return school_class


def _my_teacher_memberships() -> set[uuid.UUID]:
    """The logged-in user's active teacher memberships in this school."""
    return set(
        db.session.scalars(
            select(Membership.id).where(
                Membership.user_id == g.current_user.id,
                Membership.school_id == current_school().id,
                Membership.role == TEACHER_ROLE,
                Membership.is_active.is_(True),
            )
        )
    )


def _teachers(classes: list[SchoolClass]) -> dict[uuid.UUID, list[ClassTeacherOut]]:
    """Each class's teachers, by name."""
    by_class: dict[uuid.UUID, list[ClassTeacherOut]] = {c.id: [] for c in classes}
    if not classes:
        return by_class
    rows = db.session.execute(
        select(ClassTeacher.class_id, Membership.id, Membership.is_active, User.full_name)
        .join(Membership, ClassTeacher.membership_id == Membership.id)
        .join(User, Membership.user_id == User.id)
        .where(ClassTeacher.class_id.in_(by_class))
        .order_by(User.full_name, Membership.id)
    )
    for class_id, membership_id, is_active, full_name in rows:
        by_class[class_id].append(
            ClassTeacherOut(membership_id=membership_id, full_name=full_name, is_active=is_active)
        )
    return by_class


def _mine(classes: list[SchoolClass], memberships: set[uuid.UUID]) -> tuple[set, dict]:
    """Of these classes: those the memberships are class teachers of, and the
    subjects (by name) they teach each one."""
    ids = [c.id for c in classes]
    subjects: dict[uuid.UUID, list[str]] = {class_id: [] for class_id in ids}
    if not ids or not memberships:
        return set(), subjects
    class_teacher_of = set(
        db.session.scalars(
            select(ClassTeacher.class_id).where(
                ClassTeacher.class_id.in_(ids), ClassTeacher.membership_id.in_(memberships)
            )
        )
    )
    rows = db.session.execute(
        select(ClassSubject.class_id, Subject.name)
        .join(Subject, ClassSubject.subject_id == Subject.id)
        .where(
            ClassSubject.class_id.in_(ids),
            ClassSubject.id.in_(
                select(SubjectTeacher.class_subject_id).where(
                    SubjectTeacher.membership_id.in_(memberships)
                )
            ),
        )
        .order_by(func.lower(Subject.name), Subject.id)
    )
    for class_id, name in rows:
        subjects[class_id].append(name)
    return class_teacher_of, subjects


def _class_out(
    school_class: SchoolClass,
    teachers: list[ClassTeacherOut],
    *,
    is_class_teacher: bool = False,
    my_subjects: list[str] | None = None,
) -> dict:
    return SchoolClassOut(
        id=school_class.id,
        academic_year_id=school_class.academic_year_id,
        grade=school_class.grade,
        grade_name=GRADES[school_class.grade],
        stream=school_class.stream,
        name=school_class.name,
        teachers=teachers,
        is_class_teacher=is_class_teacher,
        my_subjects=my_subjects or [],
    ).model_dump(mode="json")


def _one_class_json(school_class: SchoolClass) -> dict:
    return _class_out(school_class, _teachers([school_class])[school_class.id])


def _sort_key(school_class: SchoolClass) -> tuple:
    return (GRADE_ORDER[school_class.grade], school_class.stream or "")


def _save(school_class: SchoolClass) -> None:
    """Flush; a grade and stream already used in the year becomes a 409."""
    # Read before flushing: after a rollback the class would be reloaded in
    # a new transaction with no school set, and Row-Level Security hides it.
    name = school_class.name
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise ApiError(409, "class_exists", f"This school year already has {name}.") from None
        raise


@classes_bp.get("")
@permission_required(CLASSES_READ, CLASSES_READ_OWN)
def list_classes():
    query = parse_query(ClassListQuery)
    year = _find_year(query.academic_year_id)
    if year is None:
        raise ApiError(404, "not_found", YEAR_NOT_FOUND)

    statement = select(SchoolClass).where(SchoolClass.academic_year_id == year.id)
    sees_all = CLASSES_READ in current_permissions()
    mine = _my_teacher_memberships()
    if not sees_all:
        # A teacher sees only the classes they are an active class teacher
        # of, or teach a subject to.
        statement = statement.where(
            SchoolClass.id.in_(
                select(ClassTeacher.class_id).where(ClassTeacher.membership_id.in_(mine))
            )
            | SchoolClass.id.in_(
                select(ClassSubject.class_id)
                .join(SubjectTeacher, SubjectTeacher.class_subject_id == ClassSubject.id)
                .where(SubjectTeacher.membership_id.in_(mine))
            )
        )
    classes = sorted(db.session.scalars(statement), key=_sort_key)
    teachers = _teachers(classes)
    class_teacher_of, my_subjects = _mine(classes, mine)
    if not sees_all:
        # Former teachers of the class are an administrator's concern only.
        teachers = {key: [t for t in value if t.is_active] for key, value in teachers.items()}

    grades = [GradeOut(code=code, name=GRADES[code]) for code in grades_in(year.starts_on.year)]
    return jsonify(
        {
            "academic_year": {"id": str(year.id), "name": year.name},
            "grades": [grade.model_dump() for grade in grades],
            "classes": [
                _class_out(
                    c,
                    teachers[c.id],
                    is_class_teacher=c.id in class_teacher_of,
                    my_subjects=my_subjects[c.id],
                )
                for c in classes
            ],
        }
    )


@classes_bp.post("")
@permission_required(CLASSES_MANAGE)
def create_class():
    data = parse_json_body(CreateClassRequest)
    school_id = current_school().id
    year = _find_year(data.academic_year_id)
    if year is None:
        raise _invalid(YEAR_NOT_FOUND)
    problem = _grade_problem(data.grade, year)
    if problem:
        raise _invalid(problem)

    school_class = SchoolClass(
        school_id=school_id, academic_year_id=year.id, grade=data.grade, stream=data.stream
    )
    db.session.add(school_class)
    _save(school_class)
    class_id = school_class.id
    audit.record("class.created", school_id=school_id, target_type="class", target_id=class_id)
    body = _one_class_json(school_class)
    db.session.commit()

    current_app.logger.info("Class created: class_id=%s school_id=%s", class_id, school_id)
    return jsonify({"class": body}), 201


@classes_bp.patch("/<uuid:class_id>")
@permission_required(CLASSES_MANAGE)
def update_class(class_id: uuid.UUID):
    data = parse_json_body(UpdateClassRequest)
    school_id = current_school().id
    school_class = _find_class_for_change(class_id, "class.updated")

    if "grade" in data.model_fields_set:
        year = db.session.get(AcademicYear, school_class.academic_year_id)
        problem = _grade_problem(data.grade, year)
        if problem:
            db.session.rollback()
            raise _invalid(problem)
        school_class.grade = data.grade
    if "stream" in data.model_fields_set:
        school_class.stream = data.stream
    _save(school_class)
    audit.record("class.updated", school_id=school_id, target_type="class", target_id=class_id)
    body = _one_class_json(school_class)
    db.session.commit()

    current_app.logger.info("Class updated: class_id=%s", class_id)
    return jsonify({"class": body})


@classes_bp.post("/<uuid:class_id>/teachers")
@permission_required(CLASSES_MANAGE)
def assign_teacher(class_id: uuid.UUID):
    data = parse_json_body(AssignTeacherRequest)
    school_id = current_school().id
    school_class = _find_class_for_change(class_id, "class_teacher.added")

    membership = db.session.scalar(
        select(Membership).where(
            Membership.id == data.membership_id,
            Membership.school_id == school_id,
            Membership.role == TEACHER_ROLE,
            Membership.is_active.is_(True),
        )
    )
    if membership is None:
        db.session.rollback()
        raise _invalid("Choose an active teacher of this school.")

    db.session.add(
        ClassTeacher(school_id=school_id, class_id=school_class.id, membership_id=membership.id)
    )
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise ApiError(
                409, "already_assigned", "This teacher is already a class teacher of this class."
            ) from None
        raise
    audit.record(
        "class_teacher.added", school_id=school_id, target_type="class", target_id=class_id
    )
    body = _one_class_json(school_class)
    db.session.commit()

    current_app.logger.info(
        "Class teacher added: class_id=%s membership_id=%s", class_id, membership.id
    )
    return jsonify({"class": body}), 201


@classes_bp.delete("/<uuid:class_id>/teachers/<uuid:membership_id>")
@permission_required(CLASSES_MANAGE)
def remove_teacher(class_id: uuid.UUID, membership_id: uuid.UUID):
    school_id = current_school().id
    school_class = _find_class_for_change(class_id, "class_teacher.removed")

    assignment = db.session.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == school_class.id, ClassTeacher.membership_id == membership_id
        )
    )
    if assignment is None:
        db.session.rollback()
        raise ApiError(404, "not_found", "That teacher is not a class teacher of this class.")

    db.session.delete(assignment)
    db.session.flush()
    audit.record(
        "class_teacher.removed", school_id=school_id, target_type="class", target_id=class_id
    )
    body = _one_class_json(school_class)
    db.session.commit()

    current_app.logger.info(
        "Class teacher removed: class_id=%s membership_id=%s", class_id, membership_id
    )
    return jsonify({"class": body})
