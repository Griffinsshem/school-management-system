"""Schemas for invitations."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.passwords import MAX_PASSWORD_LENGTH
from app.models.membership import ROLES
from app.models.user import MAX_EMAIL_LENGTH, MAX_NAME_LENGTH, normalize_email, validate_email

Role = Literal[ROLES]  # type: ignore[valid-type]
MAX_TOKEN_LENGTH = 128


def _valid_email(value: str) -> str:
    value = normalize_email(value)
    validate_email(value)  # EmailFormatError is a ValueError: reported as a 422.
    return value


class CreateInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH + 10)
    role: Role

    _email = field_validator("email")(_valid_email)


class PlatformInvitationRequest(BaseModel):
    """A platform administrator invites a school's administrator."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH + 10)

    _email = field_validator("email")(_valid_email)


class InvitationOut(BaseModel):
    """An invitation as its school sees it. Never includes the token."""

    id: uuid.UUID
    email: str
    role: str
    status: Literal["pending", "accepted", "revoked", "expired"]
    created_at: datetime
    expires_at: datetime


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=MAX_TOKEN_LENGTH)


class AcceptInvitationRequest(BaseModel):
    """Accept an invitation. Name and password are needed only for a new account."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=MAX_TOKEN_LENGTH)
    full_name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    password: str | None = Field(default=None, min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("full_name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Must not be blank.")
        return value
