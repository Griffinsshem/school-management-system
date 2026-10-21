"""Failed login attempts, used for rate limiting.

Neither email addresses nor IP addresses are stored: each row holds a keyed
hash (HMAC-SHA-256) that cannot be turned back into the original value.
Rows older than the rate-limit window are deleted.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

KEY_TYPES = ("account", "ip")


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"
    __table_args__ = (
        CheckConstraint("key_type IN ('account', 'ip')", name="key_type_valid"),
        Index("ix_login_attempts_lookup", "key_type", "key_hash", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key_type: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64))
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
