"""The users table: one login identity per person."""

import re
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, false, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

MAX_EMAIL_LENGTH = 254
MAX_NAME_LENGTH = 200

# A deliberately simple shape check. Real proof of ownership comes from the
# invitation link sent to the address (feature B5).
_EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class EmailFormatError(ValueError):
    """The email address is not acceptable. The message is safe to show users."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> None:
    """Check an already-normalized email address."""
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_SHAPE.fullmatch(email):
        raise EmailFormatError("Enter a valid email address.")


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        # The database itself refuses un-normalized emails, so "Ann@x.com"
        # and "ann@x.com" can never become two accounts.
        CheckConstraint("email = lower(btrim(email))", name="email_normalized"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(MAX_EMAIL_LENGTH), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Granted only by the `flask create-platform-admin` terminal command.
    is_platform_admin: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        # The ID only: emails and names are personal data and must not end up in logs.
        return f"<User {self.id}>"
