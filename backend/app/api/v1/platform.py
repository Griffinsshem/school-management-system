"""Platform administration: managing the schools on the platform.

Only platform administrators can use these endpoints. Being a platform
administrator does not give access to any school's own data; that needs a
membership in the school.
"""

import uuid

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import audit
from app import invitations as invitation_service
from app.auth.sessions import platform_admin_required
from app.errors import ApiError
from app.extensions import db
from app.models import School
from app.schemas import parse_json_body
from app.schemas.invitations import PlatformInvitationRequest
from app.schemas.schools import CreateSchoolRequest, SchoolOut
from app.school_context import set_database_school

platform_bp = Blueprint("platform", __name__, url_prefix="/platform")

CODE_TAKEN = "A school with that code already exists."


def _school_json(school: School) -> dict:
    return SchoolOut.model_validate(school).model_dump(mode="json")


@platform_bp.post("/schools")
@platform_admin_required
def create_school():
    data = parse_json_body(CreateSchoolRequest)
    if db.session.scalar(select(School.id).where(School.code == data.code)) is not None:
        raise ApiError(409, "school_code_taken", CODE_TAKEN)

    school = School(name=data.name, code=data.code, county_code=data.county_code)
    db.session.add(school)
    try:
        db.session.flush()  # Assigns the ID for the audit event.
        audit.record(
            "school.created", school_id=school.id, target_type="school", target_id=school.id
        )
        db.session.commit()
    except IntegrityError:
        # Another request created the same code at the same moment.
        db.session.rollback()
        raise ApiError(409, "school_code_taken", CODE_TAKEN) from None

    current_app.logger.info(
        "School created: school_id=%s by user_id=%s", school.id, g.current_user.id
    )
    return jsonify({"school": _school_json(school)}), 201


@platform_bp.get("/schools")
@platform_admin_required
def list_schools():
    schools = db.session.scalars(select(School).order_by(School.name, School.code))
    return jsonify({"schools": [_school_json(school) for school in schools]}), 200


@platform_bp.post("/schools/<uuid:school_id>/invitations")
@platform_admin_required
def invite_school_admin(school_id: uuid.UUID):
    """Invite a school's administrator, for example its first one."""
    data = parse_json_body(PlatformInvitationRequest)
    school = db.session.get(School, school_id)
    if school is None or not school.is_active:
        raise ApiError(404, "not_found", "School not found.")

    # The platform administrator is not a member of the school, so the
    # school is set for this transaction explicitly (Row-Level Security).
    set_database_school(school.id)
    invitation, token = invitation_service.create(school, data.email, "school_admin")
    body = {
        "invitation": invitation_service.to_json(invitation),
        "accept_url": invitation_service.accept_url(token),
    }
    invitation_id = invitation.id
    db.session.commit()
    current_app.logger.info(
        "Invitation created: invitation_id=%s school_id=%s", invitation_id, school_id
    )
    return jsonify(body), 201
