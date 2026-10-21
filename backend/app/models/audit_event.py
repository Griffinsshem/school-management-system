"""The audit trail: an append-only record of who did what.

The API's database user (sms_app) may only add and read rows; the migration
removes its UPDATE and DELETE rights, so recorded events cannot be changed
or erased through the application, even by a bug.

Events hold IDs only, never names or emails. There are deliberately no
foreign keys: an event must survive whatever happens to the rows it
mentions, and refused attempts may name IDs that do not exist.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

OUTCOMES = ("success", "denied")


class AuditEvent(db.Model):
    __tablename__ = "audit_events"
    __table_args__ = (
        # For example "membership.deactivated": lowercase words, one dot.
        CheckConstraint("action ~ '^[a-z_]+\\.[a-z_]+$'", name="action_format"),
        CheckConstraint("outcome IN ('success', 'denied')", name="outcome_valid"),
        Index("ix_audit_events_school_time", "school_id", "occurred_at"),
        Index("ix_audit_events_actor_time", "actor_user_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # None when the action came from a terminal command rather than a user.
    actor_user_id: Mapped[uuid.UUID | None]
    school_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[uuid.UUID | None]
    outcome: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[str | None] = mapped_column(String(64))

    def __repr__(self) -> str:
        return f"<AuditEvent {self.id} {self.action}>"
