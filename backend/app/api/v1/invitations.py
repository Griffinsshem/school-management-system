"""Invitation endpoints.

- /school/invitations: a school's administrators invite, list and revoke
  (the school comes from the session, as everywhere else).
- /invitations/preview and /invitations/accept: used by the invitee, who
  may have no account and no school yet. The token is always sent in the
  JSON body, never in the URL.
"""

import uuid

from flask import Blueprint, current_app, jsonify
from sqlalchemy import select

from app import invitations as service
from app.auth.permissions import MEMBERS_MANAGE, MEMBERS_READ, permission_required
from app.auth.schools import current_school, only_school_id
from app.auth.sessions import set_session_cookie, start_session
from app.extensions import db
from app.models import Invitation, School, User
from app.schemas import parse_json_body
from app.schemas.auth import UserOut
from app.schemas.invitations import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    TokenRequest,
)
from app.schemas.schools import SchoolOut

school_invitations_bp = Blueprint("school_invitations", __name__, url_prefix="/school/invitations")
invitations_bp = Blueprint("invitations", __name__, url_prefix="/invitations")

LIST_LIMIT = 200


@school_invitations_bp.post("")
@permission_required(MEMBERS_MANAGE)
def create_invitation():
    data = parse_json_body(CreateInvitationRequest)
    invitation, token = service.create(current_school(), data.email, data.role)
    body = {"invitation": service.to_json(invitation), "accept_url": service.accept_url(token)}
    invitation_id = invitation.id
    db.session.commit()
    current_app.logger.info("Invitation created: invitation_id=%s", invitation_id)
    # The link is shown once: only its hash is stored.
    return jsonify(body), 201


@school_invitations_bp.get("")
@permission_required(MEMBERS_READ)
def list_invitations():
    invitations = db.session.scalars(
        select(Invitation)
        .where(Invitation.school_id == current_school().id)
        .order_by(Invitation.created_at.desc(), Invitation.id)
        .limit(LIST_LIMIT)
    )
    return jsonify({"invitations": [service.to_json(i) for i in invitations]})


@school_invitations_bp.post("/<uuid:invitation_id>/revoke")
@permission_required(MEMBERS_MANAGE)
def revoke_invitation(invitation_id: uuid.UUID):
    invitation = service.revoke(invitation_id, current_school())
    return jsonify({"invitation": service.to_json(invitation)})


@invitations_bp.post("/preview")
def preview_invitation():
    data = parse_json_body(TokenRequest)
    invitation = service.find_usable(data.token, "invitation.previewed")
    school = db.session.scalar(select(School).where(School.id == invitation.school_id))
    has_account = (
        db.session.scalar(select(User.id).where(User.email == invitation.email)) is not None
    )
    return jsonify(
        {
            "invitation": {
                "email": invitation.email,
                "role": invitation.role,
                "expires_at": invitation.expires_at.isoformat(),
                "school": SchoolOut.model_validate(school).model_dump(mode="json"),
                # Tells the page whether to ask the invitee to log in or to
                # create an account. Only the holder of the link sees it.
                "has_account": has_account,
            }
        }
    )


@invitations_bp.post("/accept")
def accept_invitation():
    data = parse_json_body(AcceptInvitationRequest)
    user, invitation, account_created = service.accept(data.token, data.full_name, data.password)
    school_id = invitation.school_id
    body = {
        "user": UserOut.model_validate(user).model_dump(mode="json"),
        "role": invitation.role,
        "school_id": str(school_id),
        "account_created": account_created,
    }
    response = jsonify(body)
    if account_created:
        # A new account is signed in straight away, into its only school.
        token = start_session(user, active_school_id=only_school_id(user))
        db.session.commit()
        set_session_cookie(response, token)
    return response, 201 if account_created else 200
