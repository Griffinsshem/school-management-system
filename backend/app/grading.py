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


def uses_weights(weights: list[int | None]) -> bool:
    """Whether a subject's term result is weighted (D6): only when every one
    of the term's assessments has a weight and they add up to exactly 100."""
    return bool(weights) and all(w is not None for w in weights) and sum(weights) == 100


def term_result(
    sat: list[tuple[Decimal, int, int | None]], bands: tuple[Band, ...], weighted: bool = False
) -> dict | None:
    """A subject's term result from the (score, maximum, weight) of each
    assessment a student sat.

    Unweighted: their scores added up, against those assessments' maximums.
    Weighted: each assessment's percentage counts by its weight; weights of
    assessments not sat are left out, so the others are scaled up.
    """
    if not sat:
        return None
    total = sum((score for score, _, _ in sat), Decimal(0))
    out_of = sum(max_score for _, max_score, _ in sat)
    if weighted:
        weight_sat = sum(weight for _, _, weight in sat)
        exact = sum(Decimal(weight) * score / max_score for score, max_score, weight in sat)
        # A percentage of 100, as a score out of 100, so `graded` rounds it.
        result = graded(exact * 100 / weight_sat, 100, bands)
    else:
        result = graded(total, out_of, bands)
    return {"score": float(total), "max_score": out_of, "weighted": weighted, **result}


# A student's overall result for a term (D6).

KCSE_SUBJECTS_COUNTED = 7
# KCSE points back to grades, best first (12 is A, 1 is E).
KCSE_GRADE_BY_POINTS = {points: grade for grade, points in KCSE_GRADES.items()}
CBC_BAND_BY_POINTS = {band.points: band.grade for band in CBC_BANDS}


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def overall_kcse(results: list[tuple[str, int]]) -> dict | None:
    """A KCSE-style mean grade from (subject category, points) per subject.

    Mathematics and the best language always count, then the best five of
    the rest (other languages included): seven in all. A student without
    Mathematics, without a language or with fewer than seven results gets
    the mean of what they have, marked incomplete.
    """
    if not results:
        return None
    pool = sorted(results, key=lambda r: -r[1])
    counted: list[int] = []
    for category in ("mathematics", "language"):
        best = next((r for r in pool if r[0] == category), None)
        if best is not None:
            counted.append(best[1])
            pool.remove(best)
    has_core = len(counted) == 2
    counted += [points for _, points in pool[: KCSE_SUBJECTS_COUNTED - len(counted)]]
    total = sum(counted)
    mean = _round_half_up(Decimal(total) / len(counted))
    return {
        "total_points": total,
        "subjects_counted": len(counted),
        "mean_points": mean,
        "grade": KCSE_GRADE_BY_POINTS[mean],
        "complete": has_core and len(counted) == KCSE_SUBJECTS_COUNTED,
    }


def overall_cbc(points: list[int], subjects_assessed: int) -> dict | None:
    """Total and average points across subjects (CBC), the average shown as
    its band. Complete when the student has a result in every subject that
    was assessed this term."""
    if not points:
        return None
    mean = _round_half_up(Decimal(sum(points)) / len(points))
    return {
        "total_points": sum(points),
        "subjects_counted": len(points),
        "mean_points": mean,
        "grade": CBC_BAND_BY_POINTS[mean],
        "complete": len(points) == subjects_assessed,
    }


def positions(scores: dict[str, int]) -> dict[str, int]:
    """Class positions from each student's total points, ties sharing a
    place (1, 2, 2, 4). Only students with a complete result are given."""
    ordered = sorted(scores.values(), reverse=True)
    return {student: ordered.index(total) + 1 for student, total in scores.items()}
