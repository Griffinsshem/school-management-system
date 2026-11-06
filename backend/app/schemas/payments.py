"""Schemas for fee payments (E2): recording a payment against a bill,
cancelling one, and the day whose payments to list.

Amounts are whole Kenyan shillings given as JSON integers: 1500.5, "1500"
and true are refused, so nothing is ever rounded or guessed. References are
trimmed; an M-Pesa code is accepted in any case and stored in capitals. A
blank "paid by" means nobody was named. Whether the date is in the future
or more than a year back is checked by the endpoint (it needs today's date
in Kenya). Error messages never repeat what was typed.
"""

import datetime as dt
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from app.models.payments import (
    MAX_CANCEL_REASON_LENGTH,
    MAX_PAID_BY_LENGTH,
    MAX_PAYMENT_AMOUNT,
    MAX_REFERENCE_LENGTH,
    MPESA_CODE_PATTERN,
)
from app.schemas.fees import _one_line

METHOD_NAMES = {"cash": "Cash", "mpesa": "M-Pesa", "bank": "Bank", "cheque": "Cheque"}


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" for ch in value)


class RecordPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_kes: StrictInt = Field(ge=1, le=MAX_PAYMENT_AMOUNT)
    method: Literal["cash", "mpesa", "bank", "cheque"]
    reference: StrictStr | None = Field(default=None, max_length=MAX_REFERENCE_LENGTH * 4)
    paid_on: dt.date
    paid_by: StrictStr | None = Field(default=None, max_length=MAX_PAID_BY_LENGTH * 4)

    @model_validator(mode="after")
    def _reference_fits_method(self) -> "RecordPaymentRequest":
        reference = (self.reference or "").strip()
        if self.method == "cash":
            if reference:
                raise ValueError("A cash payment has no reference. Leave the reference empty.")
            self.reference = None
        elif self.method == "mpesa":
            reference = reference.upper()
            if not re.fullmatch(MPESA_CODE_PATTERN, reference):
                raise ValueError(
                    "Enter the M-Pesa transaction code from the payment message:"
                    " 10 letters and digits, for example SJK3ABCD12."
                )
            self.reference = reference
        else:
            what = "the bank reference" if self.method == "bank" else "the cheque number"
            self.reference = _one_line(reference, what, MAX_REFERENCE_LENGTH)
        return self

    @model_validator(mode="after")
    def _paid_by_is_one_line(self) -> "RecordPaymentRequest":
        paid_by = (self.paid_by or "").strip()
        if not paid_by:
            self.paid_by = None
        elif _has_control_characters(paid_by):
            raise ValueError("Paid by must be a single line of ordinary text.")
        elif len(paid_by) > MAX_PAID_BY_LENGTH:
            raise ValueError(
                f"Paid by can be at most {MAX_PAID_BY_LENGTH} characters (this has {len(paid_by)})."
            )
        else:
            self.paid_by = paid_by
        return self


class CancelPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: StrictStr = Field(max_length=MAX_CANCEL_REASON_LENGTH * 4)

    @model_validator(mode="after")
    def _reason_is_one_line(self) -> "CancelPaymentRequest":
        self.reason = _one_line(self.reason, "a reason", MAX_CANCEL_REASON_LENGTH)
        return self


class PaymentsDayQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date | None = None
