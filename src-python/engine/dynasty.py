"""Dynasty multi-year valuation and positional age curves (MATH_MODELS.md §8).

Dynasty mode replaces the single-season baseline :math:`E[FP_i]` used by DVORP
with a discounted multi-year utility value:

    V_dynasty(i) = sum_{h=0}^{H-1} E[FP_i] * A_factor(pos, age_i + h) / (1 + r)^h

with horizon ``H = 3`` and discount rate ``r = 0.15``. The positional age
factor ``A_factor`` encodes the typical career arc of a position (running
backs peak and decline earliest; quarterbacks sustain value the longest).

All functions here are pure, allocation-light, and complete in microseconds so
the per-pick DVORP hot path stays well under the 50ms latency budget.
"""

from __future__ import annotations

from .models import PlayerProjection, Position

# Multi-year horizon and discount rate (MATH_MODELS.md §8).
DYNASTY_HORIZON: int = 3
DYNASTY_DISCOUNT_RATE: float = 0.15

# Sensible positional defaults applied when a projection carries no explicit
# age (e.g. the synthetic fallback or an ``nfl_data_py`` row missing its date
# of birth). These represent a young-but-established starter's age.
DEFAULT_AGE: dict[str, int] = {
    "QB": 25,
    "RB": 24,
    "WR": 24,
    "TE": 25,
}

# Positional age curves as ordered ``(max_age_inclusive, multiplier)`` pairs.
# The first entry whose ``max_age_inclusive`` is ``>= age`` applies, so the
# final sentinel (10_000) is the open-ended "oldest" bucket.
#
#   RB: <=25 -> 1.00, 26-27 -> 0.80, 28-29 -> 0.55, 30+ -> 0.30
#   WR: <=28 -> 1.00, 29-30 -> 0.85, 31-32 -> 0.65, 33+ -> 0.40
#   TE: <=29 -> 1.00, 30-31 -> 0.85, 32-33 -> 0.65, 34+ -> 0.40
#   QB: <=31 -> 1.00, 32-34 -> 0.90, 35-37 -> 0.75, 38+ -> 0.50
_AGE_CURVES: dict[str, list[tuple[int, float]]] = {
    "RB": [(25, 1.0), (27, 0.80), (29, 0.55), (10_000, 0.30)],
    "WR": [(28, 1.0), (30, 0.85), (32, 0.65), (10_000, 0.40)],
    "TE": [(29, 1.0), (31, 0.85), (33, 0.65), (10_000, 0.40)],
    "QB": [(31, 1.0), (34, 0.90), (37, 0.75), (10_000, 0.50)],
}


def age_factor(position: Position, age: int) -> float:
    """Positional age multiplier ``A_factor(pos, age)`` (MATH_MODELS.md §8).

    Returns ``1.0`` for positions without a defined dynasty curve (K/DST).
    """
    curves = _AGE_CURVES.get(position)
    if not curves:
        return 1.0
    for max_age, multiplier in curves:
        if age <= max_age:
            return multiplier
    return curves[-1][1]  # unreachable given the sentinel, kept defensively


def effective_age(player: PlayerProjection) -> int:
    """Return the age used for dynasty valuation, defaulting per position."""
    if player.age is not None:
        return int(player.age)
    return DEFAULT_AGE.get(player.position, 25)


def dynasty_value(
    single_year_fp: float,
    position: Position,
    age: int,
    *,
    horizon: int = DYNASTY_HORIZON,
    discount_rate: float = DYNASTY_DISCOUNT_RATE,
) -> float:
    """Discounted multi-year dynasty utility ``V_dynasty(i)``.

    ``single_year_fp`` is the player's current single-season projected fantasy
    points (``E[FP_i]``). The value is the discounted sum of the age-declined
    projections over ``horizon`` seasons:

        V = sum_{h=0}^{H-1} E[FP_i] * A_factor(pos, age + h) / (1 + r)^h

    This is intentionally *not* annualized back to a single season; the
    resulting scale is a multi-year value feed the same DVORP identity as a
    single-season projection would (see :func:`effective_projection`).
    """
    total = 0.0
    factor = 1.0
    for h in range(horizon):
        total += single_year_fp * age_factor(position, age + h) * factor
        factor /= 1.0 + discount_rate
    return float(total)


def effective_projection(player: PlayerProjection, is_dynasty: bool) -> float:
    """Return the projection value feeding the DVORP identity.

    In redraft mode this is simply ``player.fantasy_points``. In dynasty mode
    it is the multi-year ``V_dynasty(i)`` value from
    :func:`dynasty_value`, using the player's age (or a sensible positional
    default when missing).
    """
    if not is_dynasty:
        return float(player.fantasy_points)
    return dynasty_value(
        float(player.fantasy_points),
        player.position,
        effective_age(player),
    )


__all__ = [
    "DYNASTY_HORIZON",
    "DYNASTY_DISCOUNT_RATE",
    "DEFAULT_AGE",
    "age_factor",
    "effective_age",
    "dynasty_value",
    "effective_projection",
]