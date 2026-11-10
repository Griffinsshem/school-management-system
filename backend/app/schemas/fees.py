"""Schemas for school fees (E1): a grade's fee structure for a term, adding
an optional item to a bill, and adjusting a bill. E4: a structure's pay-by
date, and the filters of the list of students owing.

Amounts are whole Kenyan shillings given as JSON integers: 1500.5, "1500"
and true are refused, so nothing is ever rounded or guessed. Names and
reasons are single lines of ordinary text, trimmed.
"""

import datetime as dt
import unicodedata
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.models.fees import (
    MAX_ADJUSTMENT_REASON_LENGTH,
    MAX_FEE_AMOUNT,
    MAX_FEE_ITEM_NAME_LENGTH,
    MAX_FEE_ITEMS,
)
from app.models.school_class import GRADES


def _one_line(value: str, what: str, max_length: int) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"Enter {what}.")
    if any(unicodedata.category(ch) == "Cc" for ch in value):
        raise ValueError(f"{what.capitalize()} must be a single line of ordinary text.")
    if len(value) > max_length:
        raise ValueError(
            f"{what.capitalize()} can be at most {max_length} characters (this has {len(value)})."
        )
    return value


class FeeItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr = Field(max_length=MAX_FEE_ITEM_NAME_LENGTH * 4)
    amount_kes: StrictInt = Field(ge=1, le=MAX_FEE_AMOUNT)
    is_optional: StrictBool = False

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _one_line(value, "a name", MAX_FEE_ITEM_NAME_LENGTH)


class SaveStructureRequest(BaseModel):
    """The structure's whole list of items, in order (replacing the old one)."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeeItemIn] = Field(max_length=MAX_FEE_ITEMS)

    @model_validator(mode="after")
    def _names_differ(self) -> "SaveStructureRequest":
        # (Error messages never repeat what was typed: see app/schemas.)
        seen: set[str] = set()
        for item in self.items:
            key = item.name.casefold()
            if key in seen:
                raise ValueError("Two items have the same name. Each item needs its own name.")
            seen.add(key)
        return self


class AddBillItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fee_item_id: uuid.UUID


class AdjustBillRequest(BaseModel):
    """A correction: negative to reduce what is owed (a bursary, a mistake),
    positive to add (a replaced textbook), always with a reason."""

    model_config = ConfigDict(extra="forbid")

    amount_kes: StrictInt = Field(ge=-MAX_FEE_AMOUNT, le=MAX_FEE_AMOUNT)
    reason: StrictStr = Field(max_length=MAX_ADJUSTMENT_REASON_LENGTH * 4)

    @field_validator("amount_kes")
    @classmethod
    def _not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("An adjustment cannot be 0.")
        return value

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _one_line(value, "a reason", MAX_ADJUSTMENT_REASON_LENGTH)


class DueDateRequest(BaseModel):
    """The pay-by date as "YYYY-MM-DD", or null to remove it. Its range
    depends on the term, so the endpoint checks it."""

    model_config = ConfigDict(extra="forbid")

    due_on: dt.date | None

    @field_validator("due_on", mode="before")
    @classmethod
    def _a_date_string(cls, value: object) -> object:
        # Not a number of seconds or any other form pydantic would accept.
        if value is not None and not isinstance(value, str):
            raise ValueError("Enter the date as YYYY-MM-DD.")
        return value


class ArrearsQuery(BaseModel):
    """Filters of the list of students owing; all optional."""

    model_config = ConfigDict(extra="forbid")

    grade: str | None = None
    class_id: uuid.UUID | None = None
    overdue: bool = False
    min_kes: int | None = Field(default=None, ge=1, le=100_000_000)

    @field_validator("grade")
    @classmethod
    def _grade(cls, value: str | None) -> str | None:
        if value is not None and value not in GRADES:
            raise ValueError("Choose one of the school's grades.")
        return value
