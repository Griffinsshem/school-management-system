"""Schema for saving a school's KCSE grade boundaries (D5).

All 12 grades are sent together, each a whole percentage from 0 to 100.
That they go down from A to E, with E at 0, is checked by
app/api/v1/grading.py, which can then name the grades in its message.
"""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.models.grading import KCSE_GRADES


class SaveKcseBoundariesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundaries: dict[str, StrictInt] = Field(min_length=1)

    @field_validator("boundaries")
    @classmethod
    def _every_grade_once(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != set(KCSE_GRADES):
            raise ValueError(
                f"Send a boundary for each of {', '.join(KCSE_GRADES)}, and no others."
            )
        if any(not 0 <= percent <= 100 for percent in value.values()):
            raise ValueError("Each boundary must be a whole number from 0 to 100.")
        return value
