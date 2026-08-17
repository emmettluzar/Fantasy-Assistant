"""Make-It-Back probability and master decision utility.

Implements MATH_MODELS.md §4 and §5:

    P_MB(i, r_next) = 1 - Phi((r_next - ADP_i) / sigma_i)

    U_i(t) = alpha * DVORP_i(t) + beta * (1 - P_MB(i, r_next))
           + gamma * R_need(p) - delta * P_bye(i)

with default weights alpha = 0.40, beta = 0.35, gamma = 0.20, delta = 0.05.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from scipy.stats import norm

from .models import (
    DEFAULT_ADP_STD,
    PlayerProjection,
    Position,
    RosterSettings,
)

# Default weights from MATH_MODELS.md §5.
DEFAULT_ALPHA = 0.40
DEFAULT_BETA = 0.35
DEFAULT_GAMMA = 0.20
DEFAULT_DELTA = 0.05

# Bye-week overlap penalty applied to each additional starter on the same bye.
BYE_OVERLAP_PENALTY = 0.5


@dataclass
class DecisionWeights:
    """Tunable weights for the master decision utility."""

    alpha: float = DEFAULT_ALPHA
    beta: float = DEFAULT_BETA
    gamma: float = DEFAULT_GAMMA
    delta: float = DEFAULT_DELTA

    def __post_init__(self) -> None:
        norm_sum = self.alpha + self.beta + self.gamma + self.delta
        if norm_sum <= 0:
            raise ValueError("Decision weights must have a positive sum")


@dataclass
class UtilityComponents:
    """Decomposed decision utility for one player."""

    player_id: str
    position: Position
    dvorp: float
    p_mb: float
    r_need: float
    p_bye: float
    utility: float


# ---------------------------------------------------------------------------
# Make-It-Back probability
# ---------------------------------------------------------------------------


def make_it_back_probability(
    player: PlayerProjection,
    r_next: float,
    sigma: Optional[float] = None,
) -> float:
    """Probability the player is *not* still available at the user's next pick.

    ``sigma`` defaults to the player's historical ADP standard deviation,
    falling back to :data:`DEFAULT_ADP_STD` when missing.
    """
    adp = player.adp
    if adp is None:
        # Without an ADP we cannot model availability; treat the player as a
        # coin-flip availability bet (conservative, neutral).
        return 0.5
    sigma_i = player.adp_std if sigma is None else sigma
    if sigma_i <= 0:
        sigma_i = DEFAULT_ADP_STD
    z = (r_next - adp) / sigma_i
    # norm.cdf(z) = P(pick_before_you <= r_next); survive = 1 - that.
    return float(1.0 - norm.cdf(z))


def make_it_back_matrix(
    players: Sequence[PlayerProjection],
    r_next: float,
) -> dict[str, float]:
    """Compute P_MB for a pool of players at one pick horizon."""
    return {p.player_id: make_it_back_probability(p, r_next) for p in players}


# ---------------------------------------------------------------------------
# Roster need and bye overlap
# ---------------------------------------------------------------------------


def roster_need_factor(
    position: Position,
    roster_slots: RosterSettings,
    owned: Mapping[Position, int],
) -> float:
    """Multiplier representing need for ``position`` on the user's roster.

    The factor scales with the number of open starter slots at ``position``
    (including a fractional flex share) relative to remaining total starter
    slots. When all starters are full need collapses to the value of a
    backfill/bench add.
    """
    slots = roster_slots.positional_slots(position, include_flex=True)
    owned_count = int(owned.get(position, 0))

    # Open dedicated + flex share slots (fractional flex).
    open_slots = max(slots - owned_count, 0.0)

    total_starters = float(roster_slots.total_starters())
    total_owned = sum(int(v) for v in owned.values())
    total_open = max(total_starters - total_owned, 0.0)

    if total_open <= 0:
        return 0.1

    # Need is the share of remaining starters this position can fill, with a
    # small floor so every open position retains some consideration.
    return float(max(open_slots / total_open, 0.05))


def bye_overlap_penalty(
    player: PlayerProjection,
    starters_bye: Mapping[int, int],
    *,
    weight: float = BYE_OVERLAP_PENALTY,
) -> float:
    """Penalty when ``player`` shares a bye week with drafted starters.

    ``starters_bye`` maps bye week -> number of starters on that bye. Returns
    a value in ``[0, 1]`` so it can be weighted by ``delta``.
    """
    bye = player.bye_week
    if not bye:
        return 0.0
    overlap = starters_bye.get(bye, 0)
    if overlap <= 0:
        return 0.0
    # Saturate at 1.0 after enough overlapping starters.
    return float(1.0 - 1.0 / (1.0 + weight * overlap))


# ---------------------------------------------------------------------------
# Master decision utility
# ---------------------------------------------------------------------------


def decision_utility(
    dvorp: float,
    p_mb: float,
    r_need: float,
    p_bye: float,
    weights: Optional[DecisionWeights] = None,
) -> float:
    """Master decision utility ``U_i(t)`` (MATH_MODELS.md §5)."""
    w = weights or DecisionWeights()
    return float(
        w.alpha * dvorp
        + w.beta * (1.0 - p_mb)
        + w.gamma * r_need
        - w.delta * p_bye
    )


@dataclass
class DecisionContext:
    """Everything needed to score an available player."""

    dvorp: Mapping[str, float]
    roster_slots: RosterSettings
    owned: Mapping[Position, int] = field(default_factory=dict)
    starters_bye: Mapping[int, int] = field(default_factory=dict)
    r_next: float = 0.0
    weights: DecisionWeights = field(default_factory=DecisionWeights)


def score_decision(
    player: PlayerProjection,
    context: DecisionContext,
    *,
    dvorp: Optional[float] = None,
) -> UtilityComponents:
    """Compute the decision utility for a single player.

    Pass ``dvorp`` to avoid recomputing it; otherwise ``context.dvorp`` is
    consulted by ``player_id``.
    """
    pv = dvorp if dvorp is not None else context.dvorp.get(player.player_id, 0.0)
    p_mb = make_it_back_probability(player, context.r_next) if context.r_next > 0 else 0.0
    r_need = roster_need_factor(player.position, context.roster_slots, context.owned)
    p_bye = bye_overlap_penalty(player, context.starters_bye)
    u = decision_utility(pv, p_mb, r_need, p_bye, context.weights)
    return UtilityComponents(
        player_id=player.player_id,
        position=player.position,
        dvorp=pv,
        p_mb=p_mb,
        r_need=r_need,
        p_bye=p_bye,
        utility=u,
    )


def rank_decisions(
    players: Sequence[PlayerProjection],
    context: DecisionContext,
    *,
    dvorp_by_id: Optional[Mapping[str, float]] = None,
) -> list[UtilityComponents]:
    """Rank available players by :math:`U_i(t)` descending.

    ``dvorp_by_id`` should map ``player_id`` to its DVORP; when omitted an
    empty map is used (DVORP defaults to 0 for every player). Use the DVORP
    engine's :func:`~engine.dvorp.compute_all_dvorp` to produce this mapping.
    """
    dvorp_map = dict(dvorp_by_id or {})
    scored = [
        score_decision(p, context, dvorp=dvorp_map.get(p.player_id))
        for p in players
    ]
    scored.sort(key=lambda c: (c.utility, c.dvorp), reverse=True)
    return scored


def compute_player_dvorp_map(dvorp_results) -> dict[str, float]:
    """Convert DVORP results to a ``player_id -> dvorp`` mapping."""
    return {r.player_id: r.dvorp for r in dvorp_results}


__all__ = [
    "DecisionWeights",
    "UtilityComponents",
    "DecisionContext",
    "DEFAULT_ALPHA",
    "DEFAULT_BETA",
    "DEFAULT_GAMMA",
    "DEFAULT_DELTA",
    "make_it_back_probability",
    "make_it_back_matrix",
    "roster_need_factor",
    "bye_overlap_penalty",
    "decision_utility",
    "score_decision",
    "rank_decisions",
    "compute_player_dvorp_map",
]