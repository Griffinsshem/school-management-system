"""Endpoints inside the current school.

The school always comes from the session (`current_school()`), never from
the URL or body. IDs in the URL are looked up only within that school, so an
ID from another school gets the same 404 as one that does not exist.
"""

import uuid

from flask import Blueprint, current_app, jsonify
from sqlalchemy import func, select

from app import audit
from app.auth.permissions import MEMBERS_MANAGE, MEMBERS_READ, permission_required
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import Membership, School, User
from app.schemas.schools import MemberUserOut, SchoolMemberOut

school_bp = Blueprint("school", __name__, url_prefix="/school")


def _member_json(membership: Membership, user: User) -> dict:
    member = SchoolMemberOut(
        id=membership.id,
        role=membership.role,
        is_active=membership.is_active,
        user=MemberUserOut.model_validate(user),
    )
    return member.model_dump(mode="json")


@school_bp.get("/members")
@permission_required(MEMBERS_READ)
def list_members():
    rows = db.session.execute(
        select(Membership, User)
        .join(User, Membership.user_id == User.id)
        .where(Membership.school_id == current_school().id)
        .order_by(User.full_name, User.email, Membership.role)
    )
    return jsonify({"members": [_member_json(membership, user) for membership, user in rows]})


@school_bp.post("/members/<uuid:membership_id>/deactivate")
@permission_required(MEMBERS_MANAGE)
def deactivate_member(membership_id: uuid.UUID):
    school = current_school()
    # Lock the school's row first: membership changes in one school then run
    # one at a time, so two admins cannot each remove the other at the same
    # moment and leave the school with none.
    db.session.execute(select(School.id).where(School.id == school.id).with_for_update())

    membership = db.session.scalar(
        select(Membership).where(Membership.id == membership_id, Membership.school_id == school.id)
    )
    if membership is None:
        db.session.rollback()
        # Another school's membership looks exactly like a missing one.
        audit.record_denied(
            "membership.deactivated",
            school_id=school.id,
            target_type="membership",
            target_id=membership_id,
        )
        raise ApiError(404, "not_found", "Member not found.")

    if membership.is_active and membership.role == "school_admin":
        active_admins = db.session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.school_id == school.id,
                Membership.role == "school_admin",
                Membership.is_active.is_(True),
            )
        )
        if active_admins <= 1:
            db.session.rollback()
            raise ApiError(
                409, "last_school_admin", "A school must keep at least one school admin."
            )

    changed = membership.is_active
    if changed:
        membership.is_active = False
        audit.record(
            "membership.deactivated",
            school_id=school.id,
            target_type="membership",
            target_id=membership.id,
        )
    db.session.commit()
    if changed:
        current_app.logger.info(
            "Membership deactivated: membership_id=%s school_id=%s", membership.id, school.id
        )

    user = db.session.get(User, membership.user_id)
    return jsonify({"member": _member_json(membership, user)}), 200
