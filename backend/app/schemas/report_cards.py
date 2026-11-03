"""Schema for saving a class teacher's report card comment (D7).

A comment is plain text. It is trimmed and its line endings made "\\n".
An empty comment ("") clears it; one of only spaces is refused, so a
stray space never deletes a comment by accident. Line breaks and tabs
inside are kept; other control characters are refused (PostgreSQL cannot
store some of them, and none belong in a comment).
"""

import unicodedata

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from app.models.report_comment import MAX_COMMENT_LENGTH

# The longest input looked at, so a huge body is refused before any work.
_COMMENT_INPUT = MAX_COMMENT_LENGTH * 4
_ALLOWED_CONTROLS = {"\n", "\t"}


class SaveCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: StrictStr = Field(max_length=_COMMENT_INPUT)

    @field_validator("comment")
    @classmethod
    def _plain_text(cls, value: str) -> str:
        if value == "":
            return value  # Clears the comment.
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not value:
            raise ValueError("A comment cannot be only spaces. Leave it empty to clear it.")
        if any(unicodedata.category(ch) == "Cc" and ch not in _ALLOWED_CONTROLS for ch in value):
            raise ValueError("A comment can only contain ordinary text and line breaks.")
        if len(value) > MAX_COMMENT_LENGTH:
            raise ValueError(
                f"A comment can be at most {MAX_COMMENT_LENGTH} characters"
                f" (this one has {len(value)})."
            )
        return value
