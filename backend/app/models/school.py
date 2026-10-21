"""The schools table: each school on the platform."""

import re
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

MAX_SCHOOL_NAME_LENGTH = 200
MIN_SCHOOL_CODE_LENGTH = 3
MAX_SCHOOL_CODE_LENGTH = 50

# Lowercase letters and digits in groups joined by single hyphens,
# for example "greenfield-academy". The database checks the same rule.
_SCHOOL_CODE_SHAPE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

# Kenya's 47 counties, numbered as in the First Schedule of the Constitution
# (the order used by government systems): 1 Mombasa ... 47 Nairobi City.
# Schools store the number; names are shown from this list, so spellings
# can never drift.
KENYA_COUNTIES: dict[int, str] = {
    1: "Mombasa",
    2: "Kwale",
    3: "Kilifi",
    4: "Tana River",
    5: "Lamu",
    6: "Taita-Taveta",
    7: "Garissa",
    8: "Wajir",
    9: "Mandera",
    10: "Marsabit",
    11: "Isiolo",
    12: "Meru",
    13: "Tharaka-Nithi",
    14: "Embu",
    15: "Kitui",
    16: "Machakos",
    17: "Makueni",
    18: "Nyandarua",
    19: "Nyeri",
    20: "Kirinyaga",
    21: "Murang'a",
    22: "Kiambu",
    23: "Turkana",
    24: "West Pokot",
    25: "Samburu",
    26: "Trans Nzoia",
    27: "Uasin Gishu",
    28: "Elgeyo-Marakwet",
    29: "Nandi",
    30: "Baringo",
    31: "Laikipia",
    32: "Nakuru",
    33: "Narok",
    34: "Kajiado",
    35: "Kericho",
    36: "Bomet",
    37: "Kakamega",
    38: "Vihiga",
    39: "Bungoma",
    40: "Busia",
    41: "Siaya",
    42: "Kisumu",
    43: "Homa Bay",
    44: "Migori",
    45: "Kisii",
    46: "Nyamira",
    47: "Nairobi City",
}


class SchoolCodeError(ValueError):
    """The school code is not acceptable. The message is safe to show users."""


def normalize_school_code(code: str) -> str:
    return code.strip().lower()


def validate_school_code(code: str) -> None:
    """Check an already-normalized school code."""
    if not (
        MIN_SCHOOL_CODE_LENGTH <= len(code) <= MAX_SCHOOL_CODE_LENGTH
        and _SCHOOL_CODE_SHAPE.fullmatch(code)
    ):
        raise SchoolCodeError(
            f"School code must be {MIN_SCHOOL_CODE_LENGTH} to {MAX_SCHOOL_CODE_LENGTH} "
            "lowercase letters or digits, optionally joined by single hyphens."
        )


class School(db.Model):
    __tablename__ = "schools"
    __table_args__ = (
        CheckConstraint(
            f"length(code) BETWEEN {MIN_SCHOOL_CODE_LENGTH} AND {MAX_SCHOOL_CODE_LENGTH} "
            "AND code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="code_format",
        ),
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_trimmed"),
        CheckConstraint(f"county_code BETWEEN 1 AND {len(KENYA_COUNTIES)}", name="county_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(MAX_SCHOOL_NAME_LENGTH))
    code: Mapped[str] = mapped_column(String(MAX_SCHOOL_CODE_LENGTH), unique=True)
    county_code: Mapped[int] = mapped_column(SmallInteger)
    # Schools are deactivated, never deleted, so their records are kept.
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def county_name(self) -> str:
        return KENYA_COUNTIES[self.county_code]

    def __repr__(self) -> str:
        return f"<School {self.id}>"
