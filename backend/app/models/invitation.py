"""Invitations: how people join a school (there is no public sign-up).

The invitee receives a random token inside a link; only its SHA-256 hash is
stored, so the database cannot be used to rebuild a working link. An
invitation is used at most once, expires, and can be revoked.

Invitations belong to a school and are protected by Row-Level Security like
every school-owned table. The person accepting one has no school yet, so the
migration adds a single narrow database function that finds an invitation
by its exact token hash and nothing else (see `find_by_token_hash`).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.membership import ROLES
from app.models.user import MAX_EMAIL_LENGTH

TOKEN_HASH_LENGTH = 64  # SHA-256 as hexadecimal

_ROLE_LIST = ", ".join(f"'{role}'" for role in ROLES)
PENDING = "accepted_at IS NULL AND revoked_at IS NULL"


class Invitation(db.Model):
    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("email = lower(btrim(email))", name="email_normalized"),
        CheckConstraint(f"role IN ({_ROLE_LIST})", name="role_valid"),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        CheckConstraint("accepted_at IS NULL OR revoked_at IS NULL", name="accepted_or_revoked"),
        CheckConstraint(
            "(accepted_at IS NULL) = (accepted_by_user_id IS NULL)", name="acceptance_complete"
        ),
        # At most one pending invitation per person, role and school: a new
        # invitation replaces (revokes) the previous one.
        Index(
            "uq_invitations_one_pending",
            "school_id",
            "email",
            "role",
            unique=True,
            postgresql_where=text(PENDING),
        ),
        Index("ix_invitations_school_created", "school_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="RESTRICT"))
    email: Mapped[str] = mapped_column(String(MAX_EMAIL_LENGTH))
    role: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @classmethod
    def find_by_token_hash(cls, token_hash: str) -> "Invitation | None":
        """The invitation with exactly this token hash, in any school, or None.

        Uses the database function `invitation_by_token_hash`, the only way
        past Row-Level Security for invitations: it matches one exact hash
        and cannot list or search.
        """
        return db.session.scalar(
            db.select(cls).from_statement(
                text("SELECT * FROM invitation_by_token_hash(:token_hash)")
            ),
            {"token_hash": token_hash},
        )

    def __repr__(self) -> str:
        # The ID only: an invitee's email must not reach logs.
        return f"<Invitation {self.id}>"
