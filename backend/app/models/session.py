"""Login sessions. Only a hash of each session token is stored."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

TOKEN_HASH_LENGTH = 64  # SHA-256 as hexadecimal


class UserSession(db.Model):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Deleting a user deletes their sessions.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Moves forward with activity; the idle timeout is measured from here.
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Fixed at login: the absolute timeout.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The school this session is working in. Set only after the server has
    # checked an active membership; never taken from the request on its own.
    active_school_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schools.id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        return f"<UserSession {self.id}>"
