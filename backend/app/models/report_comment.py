"""Class teachers' comments on report cards (D7).

A report card is one student's results for one term in one class. It is
worked out each time it is shown (results from marks, attendance from
registers); only the class teacher's comment is stored, here.

Rules the database enforces itself:
- one comment per student, class and term;
- the class, the term and the school year belong together, and the student
  is of the same school (multi-column foreign keys);
- a comment is plain text of 1 to 500 characters, with no whitespace
  at either end.

Rules that need other data (the student is on the class's results; who may
write) are checked by the API. Clearing a comment deletes its row; the
audit trail records who wrote or cleared it, never the text. Comments are
personal data about children: never log them.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

MAX_COMMENT_LENGTH = 500


class ReportComment(db.Model):
    __tablename__ = "report_comments"
    __table_args__ = (
        # The class is in this school year.
        ForeignKeyConstraint(
            ["class_id", "academic_year_id", "school_id"],
            ["classes.id", "classes.academic_year_id", "classes.school_id"],
            name="fk_report_comments_class_same_year",
            ondelete="RESTRICT",
        ),
        # The term is in the same school year.
        ForeignKeyConstraint(
            ["term_id", "academic_year_id", "school_id"],
            ["terms.id", "terms.academic_year_id", "terms.school_id"],
            name="fk_report_comments_term_same_year",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["student_id", "school_id"],
            ["students.id", "students.school_id"],
            name="fk_report_comments_student_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "class_id", "term_id", "student_id", name="uq_report_comments_class_term_student"
        ),
        # Starts and ends with a visible character (no leading or trailing
        # spaces, tabs or newlines), so it is never empty.
        CheckConstraint(
            r"comment ~ '^\S' AND comment ~ '\S$'"
            f" AND char_length(comment) <= {MAX_COMMENT_LENGTH}",
            name="comment_trimmed_and_length",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    academic_year_id: Mapped[uuid.UUID] = mapped_column()
    class_id: Mapped[uuid.UUID] = mapped_column()
    term_id: Mapped[uuid.UUID] = mapped_column()
    student_id: Mapped[uuid.UUID] = mapped_column(index=True)
    comment: Mapped[str] = mapped_column(String(MAX_COMMENT_LENGTH))
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ReportComment {self.id}>"
