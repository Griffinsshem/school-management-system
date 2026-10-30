"""Assessments and marks (D4).

- An assessment belongs to one subject a class takes, in one term of the
  class's school year. Its marks are raw scores or "did not sit"; grades
  come later (D5) and are never stored.
- Who may do what (decisions of 2026-10-29):
  * school administrators (`marks.record`) add, change, lock and unlock
    assessments and enter marks for any class;
  * principals (`marks.read`) read everything;
  * teachers (`marks.record_own`) add assessments and enter marks for the
    subjects they teach (as active subject teachers), and read every
    subject's marks in the classes they are class teacher of;
  * nobody else sees marks.
- A locked assessment can be changed by school administrators only.
- Saving marks only touches the students sent; a score with neither a value
  nor "did not sit" clears that mark. Every changed mark is audited, student
  by student. Scores never go into logs or the audit trail.

Another school's class, or a class or subject the teacher may not see,
looks exactly like one that does not exist (404).
"""

import uuid
from datetime import date
from decimal import Decimal

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import audit, grading
from app.api.v1 import academic_years as years_api
from app.api.v1.enrolments import _teaches  # Active class teacher of the class.
from app.auth.permissions import (
    MARKS_READ,
    MARKS_RECORD,
    MARKS_RECORD_OWN,
    current_permissions,
    permission_required,
)
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import (
    Assessment,
    ClassSubject,
    Enrolment,
    Mark,
    Membership,
    SchoolClass,
    Student,
    Subject,
    SubjectTeacher,
    Term,
)
from app.models.school_class import TEACHER_ROLE
from app.schemas import parse_json_body, parse_query
from app.schemas.assessments import (
    CreateAssessmentRequest,
    RequiredTermQuery,
    SaveMarksRequest,
    TermQuery,
    UpdateAssessmentRequest,
)

assessments_bp = Blueprint("assessments", __name__, url_prefix="/school")

UNIQUE_VIOLATION = "23505"
NOT_FOUND = "Not found."
ASSESSMENT_NOT_FOUND = "Assessment not found."
LOCKED = "This assessment is locked. Ask a school administrator to unlock it."
# Names listed in a refusal before "and N more".
MAX_NAMES_IN_MESSAGE = 5


def _invalid(message: str) -> ApiError:
    details = [{"field": "", "message": message}]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def _names(names: list[str]) -> str:
    shown = names[:MAX_NAMES_IN_MESSAGE]
    hidden = len(names) - len(shown)
    return ", ".join(shown) + (f" and {hidden} more" if hidden else "")


def _score_text(value: Decimal | int) -> str:
    """12.0 as "12", 12.5 as "12.5"."""
    return f"{Decimal(value).normalize():f}"


# Who may see and change what.


def _teaches_subject(class_subject: ClassSubject) -> bool:
    """Whether the logged-in user is an active teacher of this class subject."""
    return (
        db.session.scalar(
            select(SubjectTeacher.id)
            .join(Membership, SubjectTeacher.membership_id == Membership.id)
            .where(
                SubjectTeacher.class_subject_id == class_subject.id,
                Membership.user_id == g.current_user.id,
                Membership.role == TEACHER_ROLE,
                Membership.is_active.is_(True),
            )
            .limit(1)
        )
        is not None
    )


def _access(school_class: SchoolClass, class_subject: ClassSubject) -> tuple[bool, bool]:
    """(may read, may write) this subject's assessments and marks in this class."""
    permissions = current_permissions()
    if MARKS_RECORD in permissions:
        return True, True
    own = MARKS_RECORD_OWN in permissions
    teaches = own and _teaches_subject(class_subject)
    reads = MARKS_READ in permissions or teaches or (own and _teaches(school_class))
    return reads, teaches


def _refuse(action: str, target_type: str, target_id: uuid.UUID, message: str = NOT_FOUND):
    audit.record_denied(
        action, school_id=current_school().id, target_type=target_type, target_id=target_id
    )
    raise ApiError(404, "not_found", message)


def _forbidden(action: str, target_id: uuid.UUID, code: str, message: str):
    audit.record_denied(
        action, school_id=current_school().id, target_type="assessment", target_id=target_id
    )
    raise ApiError(403, code, message)


def _find_class(class_id: uuid.UUID) -> SchoolClass | None:
    return db.session.scalar(
        select(SchoolClass).where(
            SchoolClass.id == class_id, SchoolClass.school_id == current_school().id
        )
    )


def _subject_for(class_id: uuid.UUID, subject_id: uuid.UUID, action: str, *, writing: bool):
    """(class, class subject, subject, may write), or a recorded refusal."""
    school_class = _find_class(class_id)
    row = (
        school_class
        and db.session.execute(
            select(ClassSubject, Subject)
            .join(Subject, ClassSubject.subject_id == Subject.id)
            .where(ClassSubject.class_id == school_class.id, ClassSubject.subject_id == subject_id)
        ).first()
    )
    if not row:
        _refuse(action, "class", class_id)
    class_subject, subject = row
    reads, writes = _access(school_class, class_subject)
    if not reads or (writing and not writes):
        _refuse(action, "class", class_id)
    return school_class, class_subject, subject, writes


def _assessment_for(assessment_id: uuid.UUID, action: str, *, writing: bool, lock: bool = False):
    """(assessment, class, class subject, subject, may write), or a recorded refusal.

    Writing to a locked assessment needs `marks.record` (403 otherwise).
    """
    query = select(Assessment).where(
        Assessment.id == assessment_id, Assessment.school_id == current_school().id
    )
    if lock:
        query = query.with_for_update()
    assessment = db.session.scalar(query)
    if assessment is None:
        _refuse(action, "assessment", assessment_id, ASSESSMENT_NOT_FOUND)
    school_class = db.session.get(SchoolClass, assessment.class_id)
    class_subject = db.session.get(ClassSubject, assessment.class_subject_id)
    subject = db.session.get(Subject, class_subject.subject_id)
    reads, writes = _access(school_class, class_subject)
    if not reads or (writing and not writes):
        _refuse(action, "assessment", assessment_id, ASSESSMENT_NOT_FOUND)
    if writing and assessment.is_locked and MARKS_RECORD not in current_permissions():
        _forbidden(action, assessment_id, "assessment_locked", LOCKED)
    return assessment, school_class, class_subject, subject, writes


# Reading.


def _terms(school_class: SchoolClass) -> list[Term]:
    return list(
        db.session.scalars(
            select(Term)
            .where(Term.academic_year_id == school_class.academic_year_id)
            .order_by(Term.number)
        )
    )


def _term_numbers(school_class: SchoolClass) -> dict[uuid.UUID, int]:
    return {term.id: term.number for term in _terms(school_class)}


def _class_json(school_class: SchoolClass) -> dict:
    return {
        "id": str(school_class.id),
        "academic_year_id": str(school_class.academic_year_id),
        "name": school_class.name,
    }


def _subject_json(subject: Subject) -> dict:
    return {"id": str(subject.id), "name": subject.name, "code": subject.code}


def _assessment_json(assessment: Assessment, term_number: int, marks_entered: int) -> dict:
    return {
        "id": str(assessment.id),
        "term": term_number,
        "name": assessment.name,
        "max_score": assessment.max_score,
        "held_on": assessment.held_on.isoformat(),
        "weight": assessment.weight,
        "is_locked": assessment.is_locked,
        "marks_entered": marks_entered,
    }


def _marks_entered(assessment_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    counts = dict.fromkeys(assessment_ids, 0)
    if assessment_ids:
        rows = db.session.execute(
            select(Mark.assessment_id, func.count())
            .where(Mark.assessment_id.in_(assessment_ids))
            .group_by(Mark.assessment_id)
        )
        counts.update({assessment_id: count for assessment_id, count in rows})
    return counts


def _class_students(class_id: uuid.UUID) -> list[Student]:
    """The class's active students."""
    return list(
        db.session.scalars(
            select(Student)
            .join(Enrolment, Enrolment.student_id == Student.id)
            .where(Enrolment.class_id == class_id, Student.is_active.is_(True))
        )
    )


def _sheet_students(assessment_ids: list[uuid.UUID], class_id: uuid.UUID) -> list[tuple]:
    """(student, in class) for the class's active students and anyone with a
    mark in these assessments, by name."""
    in_class = {student.id: student for student in _class_students(class_id)}
    others: list[Student] = []
    if assessment_ids:
        statement = select(Student).where(
            Student.id.in_(select(Mark.student_id).where(Mark.assessment_id.in_(assessment_ids)))
        )
        if in_class:
            statement = statement.where(Student.id.not_in(in_class))
        others = list(db.session.scalars(statement))
    everyone = [(s, True) for s in in_class.values()] + [(s, False) for s in others]
    return sorted(everyone, key=lambda pair: (pair[0].full_name, pair[0].admission_number))


def _mark_json(mark: Mark | None) -> dict:
    if mark is None:
        return {"score": None, "did_not_sit": False}
    return {
        "score": float(mark.score) if mark.score is not None else None,
        "did_not_sit": mark.did_not_sit,
    }


def _result(mark: Mark | None, max_score: int, bands) -> dict | None:
    """The mark's percentage and grade (D5), or None without a score."""
    return grading.graded(mark.score if mark else None, max_score, bands)


def _sheet_json(assessment, school_class, subject, writes: bool) -> dict:
    marks = {
        mark.student_id: mark
        for mark in db.session.scalars(select(Mark).where(Mark.assessment_id == assessment.id))
    }
    term_number = _term_numbers(school_class)[assessment.term_id]
    scale = grading.scale_for(school_class.grade)
    bands = grading.bands_for(scale, school_class.school_id)
    return {
        "class": _class_json(school_class),
        "subject": _subject_json(subject),
        "assessment": _assessment_json(assessment, term_number, len(marks)),
        "can_record": writes,
        "can_lock": MARKS_RECORD in current_permissions(),
        "scale": grading.scale_json(scale, bands),
        "students": [
            {
                "id": str(student.id),
                "admission_number": student.admission_number,
                "full_name": student.full_name,
                "in_class": in_class,
                **_mark_json(marks.get(student.id)),
                "result": _result(marks.get(student.id), assessment.max_score, bands),
            }
            for student, in_class in _sheet_students([assessment.id], school_class.id)
        ],
    }


def _date_problem(day: date, term: Term) -> str | None:
    if day > years_api.school_today():
        return "The date cannot be in the future."
    if not term.starts_on <= day <= term.ends_on:
        return (
            f"The date must be inside Term {term.number} "
            f"({term.starts_on.isoformat()} to {term.ends_on.isoformat()})."
        )
    return None


def _save(assessment: Assessment) -> None:
    """Flush; a name already used in the subject and term becomes a 409."""
    name = assessment.name
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise ApiError(
                409, "assessment_exists", f"This subject already has {name} in this term."
            ) from None
        raise


@assessments_bp.get("/classes/<uuid:class_id>/subjects/<uuid:subject_id>/assessments")
@permission_required(MARKS_READ, MARKS_RECORD, MARKS_RECORD_OWN)
def list_assessments(class_id: uuid.UUID, subject_id: uuid.UUID):
    query = parse_query(TermQuery)
    school_class, class_subject, subject, writes = _subject_for(
        class_id, subject_id, "assessments.read", writing=False
    )
    terms = _terms(school_class)
    numbers = {term.id: term.number for term in terms}
    statement = select(Assessment).where(Assessment.class_subject_id == class_subject.id)
    if query.term is not None:
        statement = statement.where(
            Assessment.term_id.in_([t.id for t in terms if t.number == query.term])
        )
    assessments = sorted(
        db.session.scalars(statement),
        key=lambda a: (numbers[a.term_id], a.held_on, a.name.lower()),
    )
    entered = _marks_entered([a.id for a in assessments])
    return jsonify(
        {
            "class": _class_json(school_class),
            "subject": _subject_json(subject),
            "terms": [
                {
                    "number": t.number,
                    "starts_on": t.starts_on.isoformat(),
                    "ends_on": t.ends_on.isoformat(),
                }
                for t in terms
            ],
            "students": len(_class_students(school_class.id)),
            "can_record": writes,
            "assessments": [
                _assessment_json(a, numbers[a.term_id], entered[a.id]) for a in assessments
            ],
        }
    )


# Changing assessments.


@assessments_bp.post("/classes/<uuid:class_id>/subjects/<uuid:subject_id>/assessments")
@permission_required(MARKS_RECORD, MARKS_RECORD_OWN)
def create_assessment(class_id: uuid.UUID, subject_id: uuid.UUID):
    data = parse_json_body(CreateAssessmentRequest)
    school_id = current_school().id
    school_class, class_subject, _subject, _writes = _subject_for(
        class_id, subject_id, "assessment.created", writing=True
    )
    term = next((t for t in _terms(school_class) if t.number == data.term), None)
    if term is None:
        db.session.rollback()
        raise _invalid(f"{school_class.name}'s school year has no Term {data.term}.")
    problem = _date_problem(data.held_on, term)
    if problem:
        db.session.rollback()
        raise _invalid(problem)

    assessment = Assessment(
        school_id=school_id,
        academic_year_id=school_class.academic_year_id,
        class_id=school_class.id,
        class_subject_id=class_subject.id,
        term_id=term.id,
        name=data.name,
        max_score=data.max_score,
        held_on=data.held_on,
        weight=data.weight,
        created_by_user_id=g.current_user.id,
    )
    db.session.add(assessment)
    _save(assessment)
    assessment_id = assessment.id
    audit.record(
        "assessment.created", school_id=school_id, target_type="assessment", target_id=assessment_id
    )
    body = _assessment_json(assessment, term.number, 0)
    db.session.commit()

    current_app.logger.info(
        "Assessment created: assessment_id=%s class_id=%s", assessment_id, class_id
    )
    return jsonify({"assessment": body}), 201


@assessments_bp.patch("/assessments/<uuid:assessment_id>")
@permission_required(MARKS_RECORD, MARKS_RECORD_OWN)
def update_assessment(assessment_id: uuid.UUID):
    data = parse_json_body(UpdateAssessmentRequest)
    school_id = current_school().id
    assessment, school_class, _cs, _subject, _writes = _assessment_for(
        assessment_id, "assessment.updated", writing=True, lock=True
    )
    term = db.session.get(Term, assessment.term_id)

    if "held_on" in data.model_fields_set:
        problem = _date_problem(data.held_on, term)
        if problem:
            db.session.rollback()
            raise _invalid(problem)
        assessment.held_on = data.held_on
    if "max_score" in data.model_fields_set:
        highest = db.session.scalar(
            select(func.max(Mark.score)).where(Mark.assessment_id == assessment.id)
        )
        if highest is not None and highest > data.max_score:
            db.session.rollback()
            raise _invalid(
                f"A mark of {_score_text(highest)} has already been entered: the maximum "
                f"cannot be lower than that."
            )
        assessment.max_score = data.max_score
    if "name" in data.model_fields_set:
        assessment.name = data.name
    if "weight" in data.model_fields_set:
        assessment.weight = data.weight
    _save(assessment)
    audit.record(
        "assessment.updated", school_id=school_id, target_type="assessment", target_id=assessment_id
    )
    db.session.flush()
    body = _assessment_json(assessment, term.number, _marks_entered([assessment.id])[assessment.id])
    db.session.commit()

    current_app.logger.info("Assessment updated: assessment_id=%s", assessment_id)
    return jsonify({"assessment": body})


@assessments_bp.delete("/assessments/<uuid:assessment_id>")
@permission_required(MARKS_RECORD, MARKS_RECORD_OWN)
def delete_assessment(assessment_id: uuid.UUID):
    school_id = current_school().id
    assessment, _class, _cs, _subject, _writes = _assessment_for(
        assessment_id, "assessment.deleted", writing=True, lock=True
    )
    if _marks_entered([assessment.id])[assessment.id]:
        name = assessment.name
        db.session.rollback()
        raise ApiError(
            409, "has_marks", f"{name} has marks, so it cannot be deleted. Clear them first."
        )
    db.session.delete(assessment)
    db.session.flush()
    audit.record(
        "assessment.deleted", school_id=school_id, target_type="assessment", target_id=assessment_id
    )
    db.session.commit()

    current_app.logger.info("Assessment deleted: assessment_id=%s", assessment_id)
    return jsonify({"deleted": True})


def _set_lock(assessment_id: uuid.UUID, locked: bool):
    action = "assessment.locked" if locked else "assessment.unlocked"
    school_id = current_school().id
    assessment, school_class, _cs, subject, writes = _assessment_for(
        assessment_id, action, writing=False, lock=True
    )
    if assessment.is_locked != locked:
        assessment.is_locked = locked
        assessment.locked_at = func.now() if locked else None
        assessment.locked_by_user_id = g.current_user.id if locked else None
        db.session.flush()
        audit.record(action, school_id=school_id, target_type="assessment", target_id=assessment_id)
        current_app.logger.info("Assessment %s: assessment_id=%s", action, assessment_id)
    body = _sheet_json(assessment, school_class, subject, writes)
    db.session.commit()
    return jsonify(body)


@assessments_bp.post("/assessments/<uuid:assessment_id>/lock")
@permission_required(MARKS_RECORD)
def lock_assessment(assessment_id: uuid.UUID):
    return _set_lock(assessment_id, True)


@assessments_bp.post("/assessments/<uuid:assessment_id>/unlock")
@permission_required(MARKS_RECORD)
def unlock_assessment(assessment_id: uuid.UUID):
    return _set_lock(assessment_id, False)


# Marks.


@assessments_bp.get("/assessments/<uuid:assessment_id>/marks")
@permission_required(MARKS_READ, MARKS_RECORD, MARKS_RECORD_OWN)
def get_marks(assessment_id: uuid.UUID):
    assessment, school_class, _cs, subject, writes = _assessment_for(
        assessment_id, "assessments.read", writing=False
    )
    return jsonify(_sheet_json(assessment, school_class, subject, writes))


@assessments_bp.put("/assessments/<uuid:assessment_id>/marks")
@permission_required(MARKS_RECORD, MARKS_RECORD_OWN)
def save_marks(assessment_id: uuid.UUID):
    data = parse_json_body(SaveMarksRequest)
    school_id = current_school().id
    # Locked, so two saves (or a save and a change of maximum) take turns.
    assessment, school_class, _cs, subject, writes = _assessment_for(
        assessment_id, "marks.saved", writing=True, lock=True
    )
    students = {
        student.id: student for student, _ in _sheet_students([assessment.id], school_class.id)
    }
    unknown = [mark.student_id for mark in data.marks if mark.student_id not in students]
    if unknown:
        db.session.rollback()
        raise _invalid(
            "Some of these students are not on this mark sheet. Reload it and try again."
        )
    too_high = [
        students[mark.student_id].full_name
        for mark in data.marks
        if mark.score is not None and mark.score > assessment.max_score
    ]
    if too_high:
        db.session.rollback()
        raise _invalid(
            f"Scores above the maximum of {assessment.max_score}: {_names(sorted(too_high))}."
        )

    existing = {
        mark.student_id: mark
        for mark in db.session.scalars(select(Mark).where(Mark.assessment_id == assessment.id))
    }
    user_id = g.current_user.id
    changed = 0
    for sent in data.marks:
        old = existing.get(sent.student_id)
        clear = sent.score is None and not sent.did_not_sit
        if clear:
            if old is None:
                continue
            db.session.delete(old)
        elif old is None:
            db.session.add(
                Mark(
                    school_id=school_id,
                    assessment_id=assessment.id,
                    student_id=sent.student_id,
                    score=sent.score,
                    did_not_sit=sent.did_not_sit,
                    updated_by_user_id=user_id,
                )
            )
        elif (old.score, old.did_not_sit) != (sent.score, sent.did_not_sit):
            old.score, old.did_not_sit = sent.score, sent.did_not_sit
            old.updated_by_user_id = user_id
        else:
            continue
        changed += 1
        audit.record(
            "mark.changed", school_id=school_id, target_type="student", target_id=sent.student_id
        )
    if changed:
        audit.record(
            "marks.saved", school_id=school_id, target_type="assessment", target_id=assessment.id
        )
    db.session.flush()
    body = _sheet_json(assessment, school_class, subject, writes)
    db.session.commit()

    current_app.logger.info(
        "Marks saved: assessment_id=%s marks_changed=%s", assessment.id, changed
    )
    return jsonify(body)


# A class's marks for a term, every subject.


def _overview_class(class_id: uuid.UUID, action: str) -> tuple[SchoolClass, Term]:
    """The class and term of a whole-class view (marks overview, results):
    for readers of every class's marks and for its class teacher."""
    query = parse_query(RequiredTermQuery)
    school_class = _find_class(class_id)
    permissions = current_permissions()
    allowed = school_class is not None and (
        MARKS_READ in permissions
        or MARKS_RECORD in permissions
        or (MARKS_RECORD_OWN in permissions and _teaches(school_class))
    )
    if not allowed:
        _refuse(action, "class", class_id)
    term = next((t for t in _terms(school_class) if t.number == query.term), None)
    if term is None:
        raise _invalid(f"{school_class.name}'s school year has no Term {query.term}.")
    return school_class, term


def _term_marks(school_class: SchoolClass, term: Term) -> dict:
    """Everything about a class's term marks: its subjects, assessments, each
    mark with its grade, each subject's term results (D5, weighted since D6)
    and the students to show."""
    subjects = list(
        db.session.execute(
            select(ClassSubject.id, Subject)
            .join(Subject, ClassSubject.subject_id == Subject.id)
            .where(ClassSubject.class_id == school_class.id)
            .order_by(func.lower(Subject.name), Subject.id)
        )
    )
    assessments = list(
        db.session.scalars(
            select(Assessment)
            .where(Assessment.class_id == school_class.id, Assessment.term_id == term.id)
            .order_by(Assessment.held_on, func.lower(Assessment.name))
        )
    )
    ids = [a.id for a in assessments]
    scale = grading.scale_for(school_class.grade)
    bands = grading.bands_for(scale, school_class.school_id)
    by_id = {a.id: a for a in assessments}
    marks: dict[uuid.UUID, dict] = {a.id: {} for a in assessments}
    # Per class subject and student: (score, maximum, weight) of each one sat.
    sat: dict[uuid.UUID, dict[str, list]] = {cs_id: {} for cs_id, _ in subjects}
    if ids:
        for mark in db.session.scalars(select(Mark).where(Mark.assessment_id.in_(ids))):
            student = str(mark.student_id)
            assessment = by_id[mark.assessment_id]
            marks[assessment.id][student] = {
                **_mark_json(mark),
                "result": _result(mark, assessment.max_score, bands),
            }
            if mark.score is not None:
                sat[assessment.class_subject_id].setdefault(student, []).append(
                    (mark.score, assessment.max_score, assessment.weight)
                )
    by_subject: dict[uuid.UUID, list[Assessment]] = {cs_id: [] for cs_id, _ in subjects}
    for a in assessments:
        by_subject[a.class_subject_id].append(a)
    items = []
    for cs_id, subject in subjects:
        weights = [a.weight for a in by_subject[cs_id]]
        weighted = grading.uses_weights(weights)
        items.append(
            {
                "class_subject_id": cs_id,
                "subject": subject,
                "assessments": by_subject[cs_id],
                "weighted": weighted,
                "weight_total": sum(w for w in weights if w is not None),
                "term_results": {
                    student: grading.term_result(entries, bands, weighted)
                    for student, entries in sat[cs_id].items()
                },
            }
        )
    return {
        "scale": scale,
        "bands": bands,
        "marks": marks,
        "subjects": items,
        "students": _sheet_students(ids, school_class.id),
    }


def _term_json(term: Term) -> dict:
    return {
        "number": term.number,
        "starts_on": term.starts_on.isoformat(),
        "ends_on": term.ends_on.isoformat(),
    }


def _student_json(student: Student, in_class: bool) -> dict:
    return {
        "id": str(student.id),
        "admission_number": student.admission_number,
        "full_name": student.full_name,
        "in_class": in_class,
    }


def _weighting_json(item: dict) -> dict:
    return {"weighted": item["weighted"], "weight_total": item["weight_total"]}


@assessments_bp.get("/classes/<uuid:class_id>/marks")
@permission_required(MARKS_READ, MARKS_RECORD, MARKS_RECORD_OWN)
def class_marks(class_id: uuid.UUID):
    school_class, term = _overview_class(class_id, "marks.read")
    data = _term_marks(school_class, term)
    return jsonify(
        {
            "class": _class_json(school_class),
            "term": _term_json(term),
            "students": [_student_json(s, in_class) for s, in_class in data["students"]],
            "scale": grading.scale_json(data["scale"], data["bands"]),
            "subjects": [
                {
                    "subject": _subject_json(item["subject"]),
                    "assessments": [
                        {
                            **_assessment_json(a, term.number, len(data["marks"][a.id])),
                            "marks": data["marks"][a.id],
                        }
                        for a in item["assessments"]
                    ],
                    **_weighting_json(item),
                    # A term result for each student who sat something.
                    "term_results": item["term_results"],
                }
                for item in data["subjects"]
            ],
        }
    )


# A class's term results (D6): each subject's result, the overall result and,
# if the school shows them, class positions.


@assessments_bp.get("/classes/<uuid:class_id>/results")
@permission_required(MARKS_READ, MARKS_RECORD, MARKS_RECORD_OWN)
def class_results(class_id: uuid.UUID):
    school_class, term = _overview_class(class_id, "results.read")
    data = _term_marks(school_class, term)
    assessed = [item for item in data["subjects"] if item["assessments"]]
    students = []
    for student, in_class in data["students"]:
        key = str(student.id)
        results = {
            str(item["subject"].id): item["term_results"][key]
            for item in assessed
            if key in item["term_results"]
        }
        if data["scale"] == grading.KCSE:
            overall = grading.overall_kcse(
                [
                    (item["subject"].kcse_category, item["term_results"][key]["points"])
                    for item in assessed
                    if key in item["term_results"]
                ]
            )
        else:
            overall = grading.overall_cbc([r["points"] for r in results.values()], len(assessed))
        students.append(
            {**_student_json(student, in_class), "results": results, "overall": overall}
        )

    show_positions = current_school().show_class_positions
    if show_positions:
        ranked = grading.positions(
            {
                s["id"]: s["overall"]["total_points"]
                for s in students
                if s["in_class"] and s["overall"] and s["overall"]["complete"]
            }
        )
        for s in students:
            s["position"] = ranked.get(s["id"])
    return jsonify(
        {
            "class": _class_json(school_class),
            "term": _term_json(term),
            "scale": grading.scale_json(data["scale"], data["bands"]),
            "show_positions": show_positions,
            "subjects": [
                {
                    **_subject_json(item["subject"]),
                    "kcse_category": item["subject"].kcse_category,
                    **_weighting_json(item),
                }
                for item in assessed
            ],
            "students": students,
        }
    )
