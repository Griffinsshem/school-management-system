"""Grading scales (D5).

- Everyone who can see marks sees the scales: the fixed CBC/KJSEA bands
  and the school's KCSE boundaries (the defaults until the school saves
  its own).
- School administrators (`grading.manage`) save the KCSE boundaries, all
  12 together. They must go down from A to E, and E starts at 0, so every
  percentage gets exactly one grade. A save is audited: it re-grades every
  Form student's marks, since grades are never stored.
"""

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import select

from app import audit, grading
from app.auth.permissions import (
    GRADING_MANAGE,
    MARKS_READ,
    MARKS_RECORD,
    MARKS_RECORD_OWN,
    permission_required,
)
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import GradeBoundary, School
from app.models.grading import KCSE_GRADES
from app.schemas import parse_json_body
from app.schemas.grading import SaveKcseBoundariesRequest

grading_bp = Blueprint("grading", __name__, url_prefix="/school")


def _invalid(message: str) -> ApiError:
    details = [{"field": "boundaries", "message": message}]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def _grading_json(school_id) -> dict:
    boundaries, is_default = grading.school_kcse_boundaries(school_id)
    return {
        "cbc": grading.scale_json(grading.CBC, grading.CBC_BANDS),
        "kcse": {
            **grading.scale_json(grading.KCSE, grading.kcse_bands(boundaries)),
            "is_default": is_default,
        },
        "default_kcse": grading.DEFAULT_KCSE_BOUNDARIES,
    }


@grading_bp.get("/grading")
@permission_required(MARKS_READ, MARKS_RECORD, MARKS_RECORD_OWN)
def get_grading():
    return jsonify(_grading_json(current_school().id))


@grading_bp.put("/grading/kcse")
@permission_required(GRADING_MANAGE)
def save_kcse_boundaries():
    data = parse_json_body(SaveKcseBoundariesRequest)
    sent = data.boundaries
    order = list(KCSE_GRADES)
    if sent["E"] != 0:
        raise _invalid("E must start at 0, so that every percentage gets a grade.")
    for better, worse in zip(order, order[1:], strict=False):
        if sent[better] <= sent[worse]:
            raise _invalid(
                f"{better} must start higher than {worse} "
                f"({sent[better]} is not above {sent[worse]})."
            )

    school_id = current_school().id
    # Saves for one school then run one at a time, so two first saves
    # cannot both insert rows.
    db.session.execute(select(School.id).where(School.id == school_id).with_for_update())
    existing = {
        row.grade: row
        for row in db.session.scalars(
            select(GradeBoundary).where(GradeBoundary.school_id == school_id)
        )
    }
    user_id = g.current_user.id
    changed = False
    for grade in order:
        row = existing.get(grade)
        if row is None:
            db.session.add(
                GradeBoundary(
                    school_id=school_id,
                    grade=grade,
                    min_percent=sent[grade],
                    updated_by_user_id=user_id,
                )
            )
            changed = True
        elif row.min_percent != sent[grade]:
            row.min_percent = sent[grade]
            row.updated_by_user_id = user_id
            changed = True
    db.session.flush()
    if changed:
        audit.record(
            "grading.updated", school_id=school_id, target_type="school", target_id=school_id
        )
    body = _grading_json(school_id)
    db.session.commit()

    if changed:
        current_app.logger.info("KCSE grade boundaries saved: school_id=%s", school_id)
    return jsonify(body)
