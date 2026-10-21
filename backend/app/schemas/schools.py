"""Schemas for schools and memberships."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.school import (
    KENYA_COUNTIES,
    MAX_SCHOOL_CODE_LENGTH,
    MAX_SCHOOL_NAME_LENGTH,
    normalize_school_code,
    validate_school_code,
)


class SchoolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    county_code: int
    county_name: str
    is_active: bool


class MembershipOut(BaseModel):
    role: str
    school: SchoolOut


class CreateSchoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_SCHOOL_NAME_LENGTH)
    code: str = Field(min_length=1, max_length=MAX_SCHOOL_CODE_LENGTH)
    # Strict: the county must be a whole number, not "47" or true.
    county_code: int = Field(strict=True, ge=1, le=len(KENYA_COUNTIES))

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Name must not be blank.")
        return name

    @field_validator("code")
    @classmethod
    def code_is_well_formed(cls, code: str) -> str:
        code = normalize_school_code(code)
        validate_school_code(code)  # SchoolCodeError is a ValueError: reported as a 422.
        return code


class SelectSchoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school_id: uuid.UUID
