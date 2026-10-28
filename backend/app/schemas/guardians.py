"""Schemas for guardians (D2).

Phone numbers are accepted as people write them ("0712 345 678",
"+254 712 345678", "254712345678") and stored in one standard form,
"+254712345678". Error messages never repeat the number or email sent.
"""

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.guardian import MAX_GUARDIAN_EMAIL_LENGTH, MAX_GUARDIAN_NAME_LENGTH
from app.models.user import EmailFormatError, normalize_email, validate_email

Relationship = Literal["mother", "father", "guardian", "grandparent", "sibling", "other_relative"]

PHONE_MESSAGE = "Enter a Kenyan mobile number, such as 0712 345 678."
# Characters people put between digits.
_SEPARATORS = re.compile(r"[\s\-().]")
_STANDARD = re.compile(r"254[17][0-9]{8}")
# Long enough for any way of writing a Kenyan number, short enough to refuse junk.
MAX_PHONE_INPUT_LENGTH = 25


def normalize_phone(value: str) -> str:
    """A Kenyan mobile number in the form +2547XXXXXXXX or +2541XXXXXXXX.

    Raises ValueError (with a message safe to show) for anything else.
    """
    digits = _SEPARATORS.sub("", value)
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9:
        digits = "254" + digits
    if not _STANDARD.fullmatch(digits):
        raise ValueError(PHONE_MESSAGE)
    return "+" + digits


def _phone(value: str) -> str:
    return normalize_phone(value)


def _name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Must not be blank.")
    return value


def _email(value: str | None) -> str | None:
    if value is None:
        return None
    value = normalize_email(value)
    if not value:
        return None  # An empty box means no email.
    try:
        validate_email(value)
    except EmailFormatError as error:
        raise ValueError(str(error)) from None
    return value


class GuardianDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=MAX_GUARDIAN_NAME_LENGTH)
    phone: str = Field(min_length=1, max_length=MAX_PHONE_INPUT_LENGTH)
    email: str | None = Field(default=None, max_length=MAX_GUARDIAN_EMAIL_LENGTH)

    _check_name = field_validator("full_name")(_name)
    _check_phone = field_validator("phone")(_phone)
    _check_email = field_validator("email")(_email)


class AddGuardianRequest(GuardianDetails):
    """A new guardian for this student."""

    relationship: Relationship
    is_primary: bool = False


class LinkGuardianRequest(BaseModel):
    """An existing guardian of the school (a sibling's) for this student."""

    model_config = ConfigDict(extra="forbid")

    guardian_id: uuid.UUID
    relationship: Relationship
    is_primary: bool = False


class UpdateLinkRequest(BaseModel):
    """Only the fields sent are changed. A student always keeps one primary
    guardian, so `is_primary` can only be set to true (on another guardian)."""

    model_config = ConfigDict(extra="forbid")

    relationship: Relationship | None = None
    is_primary: Literal[True] | None = None

    @model_validator(mode="after")
    def _check(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one of relationship and is_primary.")
        if "relationship" in self.model_fields_set and self.relationship is None:
            raise ValueError("relationship must not be null.")
        return self


class UpdateGuardianRequest(BaseModel):
    """Only the fields sent are changed. `"email": null` (or "") removes it."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=MAX_GUARDIAN_NAME_LENGTH)
    phone: str | None = Field(default=None, min_length=1, max_length=MAX_PHONE_INPUT_LENGTH)
    email: str | None = Field(default=None, max_length=MAX_GUARDIAN_EMAIL_LENGTH)

    @field_validator("full_name", "phone")
    @classmethod
    def _not_null(cls, value: str | None, info) -> str:
        if value is None:
            raise ValueError("Must not be null.")
        return _name(value) if info.field_name == "full_name" else _phone(value)

    _check_email = field_validator("email")(_email)

    @model_validator(mode="after")
    def _check(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one of full_name, phone and email.")
        return self


class LookupRequest(BaseModel):
    """Find a guardian by phone. Sent in the body, never in the address."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=MAX_PHONE_INPUT_LENGTH)

    _check_phone = field_validator("phone")(_phone)
