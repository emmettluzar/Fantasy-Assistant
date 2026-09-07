"""Make-It-Back probability and master decision utility.

Implements MATH_MODELS.md §4, §5, and §6:

    P_MB(i, r_next) = 1 - Phi((r_next - ADP_i) / sigma_i)

    U_i(t) = alpha * DVORP_i(t) + beta * (1 - P_MB(i, r_next))
           + gamma * R_need(p) - delta * P_bye(i)
           + epsilon * V_upside(i)

with default weights alpha = 0.40, beta = 0.35, gamma = 0.20, delta = 0.05,
epsilon = 0.12 (upside coefficient for contingent/variance value, §6).

The final utility is multiplied by a positional scarcity multiplier S_m
(MATH_MODELS.md §7): when a player is the last (N_tier == 1) or second-to-last
(N_tier == 2) asset remaining in their positional xFP tier, S_m boosts the
score to prioritize halting a positional run.

As the user's roster fills (``user_picks`` rises), ``alpha`` decays toward
zero while ``epsilon`` scales up, shifting the engine from safe median DVORP
toward high-variance / contingent-upside targets in the final bench rounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping, Optional, Sequence

from scipy.stats import norm

from .models import (
    DEFAULT_ADP_STD,
    PlayerProjection,
    Position,
    RosterSettings,
)

# Warm up scipy's lazily-loaded special-function path so the first live pick
# event does not pay the ~100ms import/initialization overhead of ``norm.cdf``.
norm.cdf(0.0)

# Default weights from MATH_MODELS.md §5 / §6.
DEFAULT_ALPHA = 0.40
DEFAULT_BETA = 0.35
DEFAULT_GAMMA = 0.20
DEFAULT_DELTA = 0.05
DEFAULT_EPSILON = 0.12

# Bye-week overlap penalty applied to each additional starter on the same bye.
BYE_OVERLAP_PENALTY = 0.5

# Dynamic upside-shift schedule (MATH_MODELS.md §6).
# ``UPSIDE_SHIFT_AFTER`` is the user pick count at which alpha begins decaying
# and epsilon begins scaling up; ``UPSIDE_SHIFT_FULL`` is the pick count at
# which the shift saturates (bench rounds).
UPSIDE_SHIFT_AFTER = 8
UPSIDE_SHIFT_FULL = 14
UPSIDE_ALPHA_FLOOR = 0.10
UPSIDE_EPSILON_MAX = 0.30

# Positional scarcity multiplier (MATH_MODELS.md §7).
SCARCITY_LAST = 1.15
SCARCITY_SECOND_LAST = 1.05


@dataclass
class DecisionWeights:
    """Tunable weights for the master decision utility."""

    alpha: float = DEFAULT_ALPHA
    beta: float = DEFAULT_BETA
    gamma: float = DEFAULT_GAMMA
    delta: float = DEFAULT_DELTA
    epsilon: float = DEFAULT_EPSILON

    def __post_init__(self) -> None:
        norm_sum = (
            self.alpha + self.beta + self.gamma + self.delta + self.epsilon
        )
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
    upside: float
    tier_remaining: int
    scarcity: float
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


def scarcity_multiplier(tier_remaining: int) -> float:
    """Positional scarcity multiplier ``S_m`` (MATH_MODELS.md §7).

    ``S_m = 1.15`` when the player is the last asset in their tier
    (``N_tier == 1``), ``1.05`` when two remain (``N_tier == 2``), and
    ``1.0`` otherwise.
    """
    if tier_remaining <= 1:
        return SCARCITY_LAST
    if tier_remaining == 2:
        return SCARCITY_SECOND_LAST
    return 1.0


def compute_tier_remaining_map(
    players: Sequence[PlayerProjection],
) -> dict[tuple[Position, int], int]:
    """Count available players per ``(position, tier)`` pair.

    The returned counts are the live ``N_tier`` values for run detection:
    for each available player we can look up how many remain in their
    positional xFP tier.
    """
    counts: dict[tuple[Position, int], int] = {}
    for p in players:
        key = (p.position, int(getattr(p, "tier", 0)))
        counts[key] = counts.get(key, 0) + 1
    return counts


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


def dvorp_to_unit(dvorp: float) -> float:
    """Map signed DVORP to a 0-1 positive scale via a soft logistic squeeze.

    This keeps the ``alpha`` coefficient monotonic in the same positive range
    as ``upside_score`` so the dynamic alpha/epsilon re-weighting is directly
    interpretable: a zero/negative DVORP maps to ~0, a large positive DVORP
    saturates toward 1.
    """
    if dvorp <= 0:
        return 0.0
    return float(dvorp / (dvorp + 5.0))


def decision_utility(
    dvorp: float,
    p_mb: float,
    r_need: float,
    p_bye: float,
    upside: float = 0.0,
    weights: Optional[DecisionWeights] = None,
) -> float:
    """Master decision utility ``U_i(t)`` (MATH_MODELS.md §5/§6)."""
    w = weights or DecisionWeights()
    return float(
        w.alpha * dvorp
        + w.beta * (1.0 - p_mb)
        + w.gamma * r_need
        - w.delta * p_bye
        + w.epsilon * upside
    )


def dynamic_upside_weights(
    weights: DecisionWeights,
    user_picks: int,
) -> DecisionWeights:
    """Scale ``alpha`` down and ``epsilon`` up as the roster fills (§6).

    Early in the draft (``user_picks <= UPSIDE_SHIFT_AFTER``) weights are
    unchanged. Between ``UPSIDE_SHIFT_AFTER`` and ``UPSIDE_SHIFT_FULL`` the
    safety/DVORP weight ``alpha`` decays linearly toward
    :data:`UPSIDE_ALPHA_FLOOR` while the upside weight ``epsilon`` rises
    linearly toward :data:`UPSIDE_EPSILON_MAX`. Past ``UPSIDE_SHIFT_FULL``
    the shift is saturated.
    """
    if user_picks <= UPSIDE_SHIFT_AFTER:
        return weights
    span = max(UPSIDE_SHIFT_FULL - UPSIDE_SHIFT_AFTER, 1)
    t = min(max((user_picks - UPSIDE_SHIFT_AFTER) / span, 0.0), 1.0)

    alpha = weights.alpha + (UPSIDE_ALPHA_FLOOR - weights.alpha) * t
    epsilon = weights.epsilon + (UPSIDE_EPSILON_MAX - weights.epsilon) * t

    return DecisionWeights(
        alpha=alpha,
        beta=weights.beta,
        gamma=weights.gamma,
        delta=weights.delta,
        epsilon=epsilon,
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
    user_picks: int = 0


def _context_with_shift(
    context: DecisionContext,
    user_picks: Optional[int] = None,
) -> DecisionContext:
    """Return a context whose weights reflect the dynamic upside shift."""
    picks = user_picks if user_picks is not None else context.user_picks
    shifted_weights = dynamic_upside_weights(context.weights, max(picks, 0))
    return replace(context, weights=shifted_weights, user_picks=max(picks, 0))


def score_decision(
    player: PlayerProjection,
    context: DecisionContext,
    *,
    dvorp: Optional[float] = None,
    tier_remaining: Optional[int] = None,
) -> UtilityComponents:
    """Compute the decision utility for a single player.

    Pass ``dvorp`` to avoid recomputing it; otherwise ``context.dvorp`` is
    consulted by ``player_id``. The signed DVORP is safely scaled to a 0-1
    positive range before multiplying by ``alpha`` so the dynamic alpha/epsilon
    shift re-weights DVORP and upside on a comparable scale.

    ``tier_remaining`` is the live count of available players sharing the
    player's positional xFP tier (``N_tier``); the final utility is
    multiplied by the scarcity multiplier :func:`scarcity_multiplier`.
    When omitted the player's static ``tier_remaining`` is used as a fallback.
    """
    pv = dvorp if dvorp is not None else context.dvorp.get(player.player_id, 0.0)
    raw_dvorp = context.dvorp.get(player.player_id, pv)
    p_mb = make_it_back_probability(player, context.r_next) if context.r_next > 0 else 0.0
    r_need = roster_need_factor(player.position, context.roster_slots, context.owned)
    p_bye = bye_overlap_penalty(player, context.starters_bye)
    upside = float(getattr(player, "upside_score", 0.0) or 0.0)
    dvorp_scaled = float(dvorp_to_unit(raw_dvorp))

    n_tier = int(
        tier_remaining
        if tier_remaining is not None
        else (getattr(player, "tier_remaining", 0) or 0)
    )
    if n_tier <= 0:
        n_tier = 1
    s_m = scarcity_multiplier(n_tier)

    u = (
        decision_utility(dvorp_scaled, p_mb, r_need, p_bye, upside, context.weights)
        * s_m
    )
    return UtilityComponents(
        player_id=player.player_id,
        position=player.position,
        dvorp=pv,
        p_mb=p_mb,
        r_need=r_need,
        p_bye=p_bye,
        upside=upside,
        tier_remaining=n_tier,
        scarcity=s_m,
        utility=u,
    )


def rank_decisions(
    players: Sequence[PlayerProjection],
    context: DecisionContext,
    *,
    dvorp_by_id: Optional[Mapping[str, float]] = None,
    user_picks: Optional[int] = None,
) -> list[UtilityComponents]:
    """Rank available players by :math:`U_i(t)` descending.

    ``dvorp_by_id`` should map ``player_id`` to its DVORP; when omitted an
    empty map is used (DVORP defaults to 0 for every player). Use the DVORP
    engine's :func:`~engine.dvorp.compute_all_dvorp` to produce this mapping.

    If ``user_picks`` is provided (or already set on ``context``) the dynamic
    upside shift scales ``alpha`` down and ``epsilon`` up as the roster fills.
    """
    effective = _context_with_shift(context, user_picks)
    dvorp_map = dict(dvorp_by_id or {})
    dvorp_lookup = dict(effective.dvorp or {})
    for player_id, value in dvorp_map.items():
        dvorp_lookup[player_id] = value
    effective.dvorp = dvorp_lookup

    tier_map = compute_tier_remaining_map(players)
    scored = [
        score_decision(
            p,
            effective,
            dvorp=dvorp_map.get(p.player_id),
            tier_remaining=tier_map.get((p.position, int(getattr(p, "tier", 0))), 1),
        )
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
    "DEFAULT_EPSILON",
    "UPSIDE_SHIFT_AFTER",
    "UPSIDE_SHIFT_FULL",
    "UPSIDE_ALPHA_FLOOR",
    "UPSIDE_EPSILON_MAX",
    "make_it_back_probability",
    "make_it_back_matrix",
    "roster_need_factor",
    "bye_overlap_penalty",
    "decision_utility",
    "dynamic_upside_weights",
    "dvorp_to_unit",
    "scarcity_multiplier",
    "compute_tier_remaining_map",
    "SCARCITY_LAST",
    "SCARCITY_SECOND_LAST",
    "score_decision",
    "rank_decisions",
    "compute_player_dvorp_map",
]
