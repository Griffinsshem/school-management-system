"""Students' guardians: parents and other contacts (D2).

Who may do what (decisions of 2026-10-28):
- School administrators and registrars (`guardians.manage`) add guardians,
  link an existing guardian to another child (siblings share one record),
  change details, choose the primary guardian and remove guardians from a
  student.
- Principals (`guardians.read`) read them. Teachers get nothing: contact
  goes through the office.

Rules:
- A phone number is stored as +2547XXXXXXXX or +2541XXXXXXXX and appears at
  most once per school (the database refuses duplicates). Adding a guardian
  whose number is already recorded is refused, so the person links the
  existing record instead. Lookups by phone take the number in the request
  body, never in the address.
- A student has at most MAX_GUARDIANS_PER_STUDENT guardians and, as soon as
  they have one, exactly one primary guardian: the first one linked becomes
  primary, choosing another moves it, and removing the primary passes it to
  the guardian linked longest ago. Changes to one student's guardians run one
  at a time (the student's row is locked).
- Guardians are corrected, never deleted; removing one from a student
  deletes only the link.

Every change is audited with IDs only; phone numbers and emails never go
into the audit trail or the logs.
"""

import uuid

from flask import Blueprint, current_app, jsonify
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.auth.permissions import GUARDIANS_MANAGE, GUARDIANS_READ, permission_required
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import Guardian, Student, StudentGuardian
from app.models.guardian import MAX_GUARDIANS_PER_STUDENT
from app.schemas import parse_json_body
from app.schemas.guardians import (
    AddGuardianRequest,
    LinkGuardianRequest,
    LookupRequest,
    UpdateGuardianRequest,
    UpdateLinkRequest,
)

guardians_bp = Blueprint("guardians", __name__, url_prefix="/school")

UNIQUE_VIOLATION = "23505"
STUDENT_NOT_FOUND = "Student not found."
GUARDIAN_NOT_FOUND = "Guardian not found."
NOT_LINKED = "That guardian is not linked to this student."
TOO_MANY = f"A student can have at most {MAX_GUARDIANS_PER_STUDENT} guardians. Remove one first."
PHONE_TAKEN = "Another guardian in this school already has that phone number."


def _student(student_id: uuid.UUID, action: str, *, lock: bool = False) -> Student:
    """The student, or a recorded refusal and 404. With `lock`, changes to
    this student's guardians then run one at a time."""
    query = select(Student).where(
        Student.id == student_id, Student.school_id == current_school().id
    )
    if lock:
        query = query.with_for_update()
    student = db.session.scalar(query)
    if student is None:
        # Another school's student looks exactly like a missing one.
        audit.record_denied(
            action, school_id=current_school().id, target_type="student", target_id=student_id
        )
        raise ApiError(404, "not_found", STUDENT_NOT_FOUND)
    return student


def _guardian(guardian_id: uuid.UUID, action: str) -> Guardian:
    guardian = db.session.scalar(
        select(Guardian).where(
            Guardian.id == guardian_id, Guardian.school_id == current_school().id
        )
    )
    if guardian is None:
        db.session.rollback()
        audit.record_denied(
            action, school_id=current_school().id, target_type="guardian", target_id=guardian_id
        )
        raise ApiError(404, "not_found", GUARDIAN_NOT_FOUND)
    return guardian


def _guardian_json(guardian: Guardian) -> dict:
    return {
        "id": str(guardian.id),
        "full_name": guardian.full_name,
        "phone": guardian.phone,
        "email": guardian.email,
    }


def _student_json(student: Student) -> dict:
    return {
        "id": str(student.id),
        "admission_number": student.admission_number,
        "full_name": student.full_name,
    }


def _links(student: Student) -> list[tuple[StudentGuardian, Guardian]]:
    """The student's guardians: the primary first, then by name."""
    rows = db.session.execute(
        select(StudentGuardian, Guardian)
        .join(Guardian, StudentGuardian.guardian_id == Guardian.id)
        .where(StudentGuardian.student_id == student.id)
        .order_by(StudentGuardian.is_primary.desc(), Guardian.full_name, Guardian.id)
    )
    return [(link, guardian) for link, guardian in rows]


def _student_guardians(student: Student) -> dict:
    return {
        "student": _student_json(student),
        "guardians": [
            {
                **_guardian_json(guardian),
                "relationship": link.relationship,
                "is_primary": link.is_primary,
            }
            for link, guardian in _links(student)
        ],  # fmt: skip
    }


def _find_link(student: Student, guardian_id: uuid.UUID) -> StudentGuardian:
    link = db.session.scalar(
        select(StudentGuardian).where(
            StudentGuardian.student_id == student.id, StudentGuardian.guardian_id == guardian_id
        )
    )
    if link is None:
        db.session.rollback()
        raise ApiError(404, "not_found", NOT_LINKED)
    return link


def _make_primary(student: Student, link: StudentGuardian) -> None:
    """Move the student's primary guardian to `link`."""
    for other in db.session.scalars(
        select(StudentGuardian).where(
            StudentGuardian.student_id == student.id,
            StudentGuardian.is_primary.is_(True),
            StudentGuardian.id != link.id,
        )
    ):
        other.is_primary = False
    db.session.flush()  # The old primary first: one primary at a time.
    link.is_primary = True


def _link_guardian(student: Student, guardian: Guardian, relationship: str, primary: bool):
    """Link a guardian to a (locked) student, keeping the rules."""
    count = db.session.scalar(
        select(func.count())
        .select_from(StudentGuardian)
        .where(StudentGuardian.student_id == student.id)
    )
    if count >= MAX_GUARDIANS_PER_STUDENT:
        db.session.rollback()
        raise ApiError(409, "too_many_guardians", TOO_MANY)
    link = StudentGuardian(
        school_id=student.school_id,
        student_id=student.id,
        guardian_id=guardian.id,
        relationship=relationship,
    )
    db.session.add(link)
    db.session.flush()
    # The first guardian is the primary one, whatever was asked.
    if primary or count == 0:
        _make_primary(student, link)
    audit.record(
        "guardian.linked", school_id=student.school_id, target_type="student", target_id=student.id
    )


def _flush_phone(step) -> None:
    """Run `step`; a phone number already recorded becomes a 409."""
    try:
        step()
    except IntegrityError as error:
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise ApiError(409, "phone_taken", PHONE_TAKEN) from None
        raise


@guardians_bp.get("/students/<uuid:student_id>/guardians")
@permission_required(GUARDIANS_READ)
def list_guardians(student_id: uuid.UUID):
    student = _student(student_id, "guardians.read")
    return jsonify(_student_guardians(student))


@guardians_bp.post("/students/<uuid:student_id>/guardians")
@permission_required(GUARDIANS_MANAGE)
def add_guardian(student_id: uuid.UUID):
    data = parse_json_body(AddGuardianRequest)
    school_id = current_school().id
    student = _student(student_id, "guardian.linked", lock=True)

    existing = db.session.scalar(
        select(Guardian).where(Guardian.school_id == school_id, Guardian.phone == data.phone)
    )
    if existing is not None:
        name = existing.full_name
        db.session.rollback()
        raise ApiError(
            409,
            "guardian_exists",
            f"{name} is already recorded with this phone number. Link them to this student "
            "instead of adding them again.",
        )
    guardian = Guardian(
        school_id=school_id, full_name=data.full_name, phone=data.phone, email=data.email
    )
    db.session.add(guardian)
    _flush_phone(db.session.flush)  # Someone added the same number just now.
    audit.record(
        "guardian.created", school_id=school_id, target_type="guardian", target_id=guardian.id
    )
    _link_guardian(student, guardian, data.relationship, data.is_primary)
    body = _student_guardians(student)
    guardian_id = guardian.id
    db.session.commit()

    current_app.logger.info("Guardian added: guardian_id=%s student_id=%s", guardian_id, student_id)
    return jsonify(body), 201


@guardians_bp.post("/students/<uuid:student_id>/guardians/link")
@permission_required(GUARDIANS_MANAGE)
def link_guardian(student_id: uuid.UUID):
    data = parse_json_body(LinkGuardianRequest)
    student = _student(student_id, "guardian.linked", lock=True)
    guardian = _guardian(data.guardian_id, "guardian.linked")
    already = db.session.scalar(
        select(StudentGuardian.id).where(
            StudentGuardian.student_id == student.id,
            StudentGuardian.guardian_id == guardian.id,
        )
    )
    if already is not None:
        db.session.rollback()
        raise ApiError(409, "already_linked", "This guardian is already linked to this student.")
    _link_guardian(student, guardian, data.relationship, data.is_primary)
    body = _student_guardians(student)
    db.session.commit()

    current_app.logger.info(
        "Guardian linked: guardian_id=%s student_id=%s", data.guardian_id, student_id
    )
    return jsonify(body), 201


@guardians_bp.patch("/students/<uuid:student_id>/guardians/<uuid:guardian_id>")
@permission_required(GUARDIANS_MANAGE)
def update_link(student_id: uuid.UUID, guardian_id: uuid.UUID):
    data = parse_json_body(UpdateLinkRequest)
    student = _student(student_id, "guardian.link_updated", lock=True)
    link = _find_link(student, guardian_id)
    changed = False
    if data.relationship is not None and data.relationship != link.relationship:
        link.relationship = data.relationship
        changed = True
    if data.is_primary and not link.is_primary:
        _make_primary(student, link)
        changed = True
    if changed:
        audit.record(
            "guardian.link_updated",
            school_id=student.school_id,
            target_type="student",
            target_id=student.id,
        )
    db.session.flush()
    body = _student_guardians(student)
    db.session.commit()

    current_app.logger.info(
        "Guardian link updated: guardian_id=%s student_id=%s", guardian_id, student_id
    )
    return jsonify(body)


@guardians_bp.delete("/students/<uuid:student_id>/guardians/<uuid:guardian_id>")
@permission_required(GUARDIANS_MANAGE)
def unlink_guardian(student_id: uuid.UUID, guardian_id: uuid.UUID):
    student = _student(student_id, "guardian.unlinked", lock=True)
    link = _find_link(student, guardian_id)
    was_primary = link.is_primary
    db.session.delete(link)
    db.session.flush()
    if was_primary:
        # The guardian linked longest ago becomes the primary one.
        successor = db.session.scalar(
            select(StudentGuardian)
            .where(StudentGuardian.student_id == student.id)
            .order_by(StudentGuardian.created_at, StudentGuardian.id)
            .limit(1)
        )
        if successor is not None:
            successor.is_primary = True
    audit.record(
        "guardian.unlinked",
        school_id=student.school_id,
        target_type="student",
        target_id=student.id,
    )
    db.session.flush()
    body = _student_guardians(student)
    db.session.commit()

    current_app.logger.info(
        "Guardian unlinked: guardian_id=%s student_id=%s", guardian_id, student_id
    )
    return jsonify(body)


@guardians_bp.patch("/guardians/<uuid:guardian_id>")
@permission_required(GUARDIANS_MANAGE)
def update_guardian(guardian_id: uuid.UUID):
    data = parse_json_body(UpdateGuardianRequest)
    guardian = _guardian(guardian_id, "guardian.updated")
    changed = False
    for field in data.model_fields_set:
        value = getattr(data, field)
        if getattr(guardian, field) != value:
            setattr(guardian, field, value)
            changed = True
    if changed:
        _flush_phone(db.session.flush)
        audit.record(
            "guardian.updated",
            school_id=guardian.school_id,
            target_type="guardian",
            target_id=guardian_id,
        )
    body = {"guardian": _guardian_json(guardian)}
    db.session.commit()

    current_app.logger.info("Guardian updated: guardian_id=%s", guardian_id)
    return jsonify(body)


@guardians_bp.post("/guardians/lookup")
@permission_required(GUARDIANS_READ)
def lookup_guardian():
    """A guardian of this school by phone number, with the students they are
    linked to (to link a sibling). The number is in the body, not the URL."""
    data = parse_json_body(LookupRequest)
    guardian = db.session.scalar(
        select(Guardian).where(
            Guardian.school_id == current_school().id, Guardian.phone == data.phone
        )
    )
    if guardian is None:
        raise ApiError(404, "not_found", "No guardian in this school has that phone number.")
    students = db.session.scalars(
        select(Student)
        .join(StudentGuardian, StudentGuardian.student_id == Student.id)
        .where(StudentGuardian.guardian_id == guardian.id)
        .order_by(Student.full_name, Student.admission_number, Student.id)
    )
    return jsonify(
        {
            "guardian": {
                **_guardian_json(guardian),
                "students": [_student_json(student) for student in students],
            }
        }
    )
