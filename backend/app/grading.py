"""Grades worked out from raw marks (D5). Grades are never stored.

Decisions of 2026-10-29:
- a mark's percentage is score / maximum x 100, rounded to a whole number
  (halves up); its grade comes from that rounded percentage, so the grade
  always matches the percentage shown;
- CBC classes (PP1 to Grade 12) use the KJSEA 8-band scale, fixed here;
- Form classes use KCSE letter grades with boundaries each school may set
  (app/models/grading.py), starting from the defaults below;
- a subject's term result adds up the scores of the term's assessments the
  student sat, against those assessments' maximums; "did not sit" and marks
  not entered are left out of both, and nothing sat means no term result.

The frontend repeats the rounding rule to show a grade while a score is
typed; the API's grade is the one that counts.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from sqlalchemy import select

from app.extensions import db
from app.models.grading import KCSE_GRADES, GradeBoundary

CBC = "cbc"
KCSE = "kcse"


class Band(NamedTuple):
    grade: str
    min_percent: int
    points: int


# KJSEA performance levels as published by KNEC (BE2 starts at 0 here so a
# score of zero still gets a grade).
CBC_BANDS: tuple[Band, ...] = (
    Band("EE1", 90, 8),
    Band("EE2", 75, 7),
    Band("ME1", 58, 6),
    Band("ME2", 41, 5),
    Band("AE1", 31, 4),
    Band("AE2", 21, 3),
    Band("BE1", 11, 2),
    Band("BE2", 0, 1),
)

# A common internal-exam default, not a KNEC rule (KNEC publishes no fixed
# KCSE cut-offs). Schools change these on the Grading page.
DEFAULT_KCSE_BOUNDARIES: dict[str, int] = {
    "A": 80,
    "A-": 75,
    "B+": 70,
    "B": 65,
    "B-": 60,
    "C+": 55,
    "C": 50,
    "C-": 45,
    "D+": 40,
    "D": 35,
    "D-": 30,
    "E": 0,
}


def scale_for(grade_level: str) -> str:
    """The scale a class uses, from its grade level (see app/models/school_class.py)."""
    return KCSE if grade_level.startswith("form_") else CBC


def percent(score: Decimal | int, max_score: Decimal | int) -> int:
    """The whole percentage, halves rounded up (12.5 / 25 -> 50, 89.5% -> 90)."""
    exact = Decimal(score) * 100 / Decimal(max_score)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def grade_for(whole_percent: int, bands: tuple[Band, ...]) -> Band:
    """The band a whole percentage falls in (bands are best first, the last starts at 0)."""
    for band in bands:
        if whole_percent >= band.min_percent:
            return band
    return bands[-1]


def kcse_bands(boundaries: dict[str, int]) -> tuple[Band, ...]:
    return tuple(Band(grade, boundaries[grade], points) for grade, points in KCSE_GRADES.items())


def school_kcse_boundaries(school_id: uuid.UUID) -> tuple[dict[str, int], bool]:
    """(the school's KCSE boundaries, whether they are still the default)."""
    saved = {
        row.grade: row.min_percent
        for row in db.session.scalars(
            select(GradeBoundary).where(GradeBoundary.school_id == school_id)
        )
    }
    if set(saved) == set(KCSE_GRADES):
        return saved, saved == DEFAULT_KCSE_BOUNDARIES
    return dict(DEFAULT_KCSE_BOUNDARIES), True


def bands_for(scale: str, school_id: uuid.UUID) -> tuple[Band, ...]:
    if scale == KCSE:
        return kcse_bands(school_kcse_boundaries(school_id)[0])
    return CBC_BANDS


def scale_json(scale: str, bands: tuple[Band, ...]) -> dict:
    return {
        "kind": scale,
        "bands": [
            {"grade": b.grade, "min_percent": b.min_percent, "points": b.points} for b in bands
        ],
    }


def graded(score: Decimal | None, max_score: int, bands: tuple[Band, ...]) -> dict | None:
    """{"percent", "grade", "points"} for a score, or None without one."""
    if score is None:
        return None
    whole = percent(score, max_score)
    band = grade_for(whole, bands)
    return {"percent": whole, "grade": band.grade, "points": band.points}


def term_result(sat: list[tuple[Decimal, int]], bands: tuple[Band, ...]) -> dict | None:
    """A subject's term result from the (score, maximum) pairs a student sat."""
    if not sat:
        return None
    total = sum((score for score, _ in sat), Decimal(0))
    out_of = sum(max_score for _, max_score in sat)
    return {
        "score": float(total),
        "max_score": out_of,
        **graded(total, out_of, bands),
    }
