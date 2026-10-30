"""Subjects, the subjects each class takes, and their teachers (D3).

- Each school keeps its own subject list. School administrators
  (`subjects.manage`) add, rename and switch subjects on and off; principals
  (`subjects.read`) see them. Subjects are never deleted: an inactive subject
  stays on the classes that already take it, but cannot be added to more.
- Administrators choose which subjects each class takes and who teaches
  each of them: active teachers of the school only, several allowed.
  Removing a subject from a class also removes its teachers there.
- A subject teacher sees the class in "My classes" and its list of students
  (names and admission numbers only); see app/api/v1/classes.py and
  app/api/v1/enrolments.py. They do not take its attendance.

Every change is audited. Another school's class or subject looks exactly
like one that does not exist (404).
"""

import uuid

from flask import Blueprint, current_app, jsonify
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.auth.permissions import SUBJECTS_MANAGE, SUBJECTS_READ, permission_required
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import (
    Assessment,
    ClassSubject,
    Membership,
    SchoolClass,
    Subject,
    SubjectTeacher,
    User,
)
from app.models.school_class import TEACHER_ROLE
from app.schemas import parse_json_body
from app.schemas.subjects import (
    AddClassSubjectRequest,
    AssignSubjectTeacherRequest,
    ClassSubjectOut,
    CreateSubjectRequest,
    SubjectOut,
    SubjectTeacherOut,
    UpdateSubjectRequest,
)

subjects_bp = Blueprint("subjects", __name__, url_prefix="/school")

UNIQUE_VIOLATION = "23505"
CLASS_NOT_FOUND = "Class not found."
SUBJECT_NOT_FOUND = "Subject not found."
NOT_TAKEN = "This class does not take that subject."


def _invalid(message: str) -> ApiError:
    details = [{"field": "", "message": message}]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def _unique_violation(error: IntegrityError) -> str | None:
    """The name of the unique constraint or index broken, if that was the error."""
    if getattr(error.orig, "sqlstate", None) != UNIQUE_VIOLATION:
        return None
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None) or ""


def _subject_json(subject: Subject) -> dict:
    return SubjectOut.model_validate(subject, from_attributes=True).model_dump(mode="json")


def _find_subject(subject_id: uuid.UUID) -> Subject | None:
    return db.session.scalar(
        select(Subject).where(Subject.id == subject_id, Subject.school_id == current_school().id)
    )


def _subject_for_change(subject_id: uuid.UUID, action: str) -> Subject:
    subject = _find_subject(subject_id)
    if subject is None:
        audit.record_denied(
            action, school_id=current_school().id, target_type="subject", target_id=subject_id
        )
        raise ApiError(404, "not_found", SUBJECT_NOT_FOUND)
    return subject


def _class_for(class_id: uuid.UUID, action: str) -> SchoolClass:
    school_class = db.session.scalar(
        select(SchoolClass).where(
            SchoolClass.id == class_id, SchoolClass.school_id == current_school().id
        )
    )
    if school_class is None:
        audit.record_denied(
            action, school_id=current_school().id, target_type="class", target_id=class_id
        )
        raise ApiError(404, "not_found", CLASS_NOT_FOUND)
    return school_class


def _find_class_subject(
    school_class: SchoolClass, subject_id: uuid.UUID, *, lock: bool = False
) -> ClassSubject | None:
    query = select(ClassSubject).where(
        ClassSubject.class_id == school_class.id, ClassSubject.subject_id == subject_id
    )
    if lock:
        query = query.with_for_update()
    return db.session.scalar(query)


def _save_subject(subject: Subject) -> None:
    """Flush; a name or code already used in the school becomes a 409."""
    # Read before flushing: after a rollback the subject would be reloaded
    # with no school set, and Row-Level Security hides it.
    name, code = subject.name, subject.code
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        constraint = _unique_violation(error)
        if constraint == "uq_subjects_school_code":
            raise ApiError(
                409, "code_taken", f"Another subject already has the code {code}."
            ) from None
        if constraint is not None:
            raise ApiError(409, "subject_exists", f"This school already has {name}.") from None
        raise


def _class_subjects(school_class: SchoolClass) -> list[dict]:
    """The subjects the class takes, by name, each with its teachers by name."""
    subjects = list(
        db.session.execute(
            select(ClassSubject.id, Subject)
            .join(Subject, ClassSubject.subject_id == Subject.id)
            .where(ClassSubject.class_id == school_class.id)
            .order_by(func.lower(Subject.name), Subject.id)
        )
    )
    teachers: dict[uuid.UUID, list[SubjectTeacherOut]] = {row[0]: [] for row in subjects}
    if teachers:
        rows = db.session.execute(
            select(
                SubjectTeacher.class_subject_id, Membership.id, Membership.is_active, User.full_name
            )
            .join(Membership, SubjectTeacher.membership_id == Membership.id)
            .join(User, Membership.user_id == User.id)
            .where(SubjectTeacher.class_subject_id.in_(teachers))
            .order_by(User.full_name, Membership.id)
        )
        for class_subject_id, membership_id, is_active, full_name in rows:
            teachers[class_subject_id].append(
                SubjectTeacherOut(
                    membership_id=membership_id, full_name=full_name, is_active=is_active
                )
            )
    return [
        ClassSubjectOut(
            subject=SubjectOut.model_validate(subject, from_attributes=True),
            teachers=teachers[class_subject_id],
        ).model_dump(mode="json")
        for class_subject_id, subject in subjects
    ]


def _class_json(school_class: SchoolClass) -> dict:
    return {
        "class": {
            "id": str(school_class.id),
            "academic_year_id": str(school_class.academic_year_id),
            "name": school_class.name,
        },
        "subjects": _class_subjects(school_class),
    }


# The school's subject list.


@subjects_bp.get("/subjects")
@permission_required(SUBJECTS_READ)
def list_subjects():
    subjects = db.session.scalars(
        select(Subject)
        .where(Subject.school_id == current_school().id)
        .order_by(func.lower(Subject.name), Subject.id)
    )
    return jsonify({"subjects": [_subject_json(s) for s in subjects]})


@subjects_bp.post("/subjects")
@permission_required(SUBJECTS_MANAGE)
def create_subject():
    data = parse_json_body(CreateSubjectRequest)
    school_id = current_school().id
    subject = Subject(school_id=school_id, name=data.name, code=data.code)
    db.session.add(subject)
    _save_subject(subject)
    subject_id = subject.id
    audit.record(
        "subject.created", school_id=school_id, target_type="subject", target_id=subject_id
    )
    body = _subject_json(subject)
    db.session.commit()

    current_app.logger.info("Subject created: subject_id=%s school_id=%s", subject_id, school_id)
    return jsonify({"subject": body}), 201


@subjects_bp.patch("/subjects/<uuid:subject_id>")
@permission_required(SUBJECTS_MANAGE)
def update_subject(subject_id: uuid.UUID):
    data = parse_json_body(UpdateSubjectRequest)
    school_id = current_school().id
    subject = _subject_for_change(subject_id, "subject.updated")

    for field in ("name", "code", "is_active", "kcse_category"):
        if field in data.model_fields_set:
            setattr(subject, field, getattr(data, field))
    _save_subject(subject)
    audit.record(
        "subject.updated", school_id=school_id, target_type="subject", target_id=subject_id
    )
    body = _subject_json(subject)
    db.session.commit()

    current_app.logger.info("Subject updated: subject_id=%s", subject_id)
    return jsonify({"subject": body})


# The subjects a class takes.


@subjects_bp.get("/classes/<uuid:class_id>/subjects")
@permission_required(SUBJECTS_READ)
def class_subjects(class_id: uuid.UUID):
    school_class = _class_for(class_id, "class_subjects.read")
    return jsonify(_class_json(school_class))


@subjects_bp.post("/classes/<uuid:class_id>/subjects")
@permission_required(SUBJECTS_MANAGE)
def add_class_subject(class_id: uuid.UUID):
    data = parse_json_body(AddClassSubjectRequest)
    school_id = current_school().id
    school_class = _class_for(class_id, "class_subject.added")

    subject = _find_subject(data.subject_id)
    if subject is None:
        db.session.rollback()
        raise _invalid(SUBJECT_NOT_FOUND)
    if not subject.is_active:
        name = subject.name
        db.session.rollback()
        raise _invalid(f"{name} is inactive. Make it active on the Subjects page first.")

    name = subject.name
    db.session.add(ClassSubject(school_id=school_id, class_id=class_id, subject_id=subject.id))
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        if _unique_violation(error) is not None:
            raise ApiError(409, "already_taken", f"This class already takes {name}.") from None
        raise
    audit.record(
        "class_subject.added", school_id=school_id, target_type="class", target_id=class_id
    )
    body = _class_json(school_class)
    db.session.commit()

    current_app.logger.info(
        "Class subject added: class_id=%s subject_id=%s", class_id, data.subject_id
    )
    return jsonify(body), 201


@subjects_bp.delete("/classes/<uuid:class_id>/subjects/<uuid:subject_id>")
@permission_required(SUBJECTS_MANAGE)
def remove_class_subject(class_id: uuid.UUID, subject_id: uuid.UUID):
    school_id = current_school().id
    school_class = _class_for(class_id, "class_subject.removed")

    # Locked, so a teacher cannot be assigned while the subject is removed.
    class_subject = _find_class_subject(school_class, subject_id, lock=True)
    if class_subject is None:
        db.session.rollback()
        raise ApiError(404, "not_found", NOT_TAKEN)

    # Assessments (D4) keep their subject: removing it would lose marks.
    if db.session.scalar(
        select(Assessment.id).where(Assessment.class_subject_id == class_subject.id).limit(1)
    ):
        name = db.session.get(Subject, subject_id).name
        db.session.rollback()
        raise ApiError(
            409,
            "has_assessments",
            f"{name} has assessments in this class, so it cannot be removed.",
        )

    db.session.execute(
        delete(SubjectTeacher).where(SubjectTeacher.class_subject_id == class_subject.id)
    )
    db.session.delete(class_subject)
    db.session.flush()
    audit.record(
        "class_subject.removed", school_id=school_id, target_type="class", target_id=class_id
    )
    body = _class_json(school_class)
    db.session.commit()

    current_app.logger.info(
        "Class subject removed: class_id=%s subject_id=%s", class_id, subject_id
    )
    return jsonify(body)


# Who teaches a subject to a class.


@subjects_bp.post("/classes/<uuid:class_id>/subjects/<uuid:subject_id>/teachers")
@permission_required(SUBJECTS_MANAGE)
def assign_subject_teacher(class_id: uuid.UUID, subject_id: uuid.UUID):
    data = parse_json_body(AssignSubjectTeacherRequest)
    school_id = current_school().id
    school_class = _class_for(class_id, "subject_teacher.added")

    class_subject = _find_class_subject(school_class, subject_id)
    if class_subject is None:
        db.session.rollback()
        raise ApiError(404, "not_found", NOT_TAKEN)
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
        SubjectTeacher(
            school_id=school_id, class_subject_id=class_subject.id, membership_id=membership.id
        )
    )
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        if _unique_violation(error) is not None:
            raise ApiError(
                409, "already_assigned", "This teacher already teaches this subject to this class."
            ) from None
        raise
    audit.record(
        "subject_teacher.added", school_id=school_id, target_type="class", target_id=class_id
    )
    body = _class_json(school_class)
    db.session.commit()

    current_app.logger.info(
        "Subject teacher added: class_id=%s subject_id=%s membership_id=%s",
        class_id,
        subject_id,
        membership.id,
    )
    return jsonify(body), 201


@subjects_bp.delete(
    "/classes/<uuid:class_id>/subjects/<uuid:subject_id>/teachers/<uuid:membership_id>"
)
@permission_required(SUBJECTS_MANAGE)
def remove_subject_teacher(class_id: uuid.UUID, subject_id: uuid.UUID, membership_id: uuid.UUID):
    school_id = current_school().id
    school_class = _class_for(class_id, "subject_teacher.removed")

    class_subject = _find_class_subject(school_class, subject_id)
    assignment = class_subject and db.session.scalar(
        select(SubjectTeacher).where(
            SubjectTeacher.class_subject_id == class_subject.id,
            SubjectTeacher.membership_id == membership_id,
        )
    )
    if not assignment:
        db.session.rollback()
        raise ApiError(404, "not_found", "That teacher does not teach this subject to this class.")

    db.session.delete(assignment)
    db.session.flush()
    audit.record(
        "subject_teacher.removed", school_id=school_id, target_type="class", target_id=class_id
    )
    body = _class_json(school_class)
    db.session.commit()

    current_app.logger.info(
        "Subject teacher removed: class_id=%s subject_id=%s membership_id=%s",
        class_id,
        subject_id,
        membership_id,
    )
    return jsonify(body)
