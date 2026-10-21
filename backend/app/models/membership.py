"""Memberships: which user belongs to which school, and in what role.

One person can hold several roles in the same school (for example a teacher
whose own child attends), so the unique key is (user, school, role).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

ROLES = (
    "school_admin",
    "principal",
    "teacher",
    "finance_officer",
    "registrar",
    "guardian",
    "student",
)

_ROLE_LIST = ", ".join(f"'{role}'" for role in ROLES)


class Membership(db.Model):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "school_id", "role", name="uq_memberships_user_school_role"),
        CheckConstraint(f"role IN ({_ROLE_LIST})", name="role_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # RESTRICT: a user or school that has memberships cannot be deleted.
    # People and schools are deactivated instead, so records are kept.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Membership {self.id}>"
