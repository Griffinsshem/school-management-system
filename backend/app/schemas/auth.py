"""Schemas for the authentication endpoints."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.auth.passwords import MAX_PASSWORD_LENGTH
from app.models.user import MAX_EMAIL_LENGTH


class LoginRequest(BaseModel):
    # Unknown fields are refused rather than silently ignored.
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserOut(BaseModel):
    """The fields of a user that the API may return. Never the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_platform_admin: bool
