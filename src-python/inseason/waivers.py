"""Rest-Of-Season DVORP and optimal FAAB bidding (Phase 5).

Two responsibilities:

1. **ROS_DVORP** — rest-of-season dynamic VORP. The regular-season-long
   :class:`~engine.models.PlayerProjection` is prorated to the remaining
   regular-season weeks (``ros_projection``), then a replacement baseline is
   computed from the currently-rostered + free-agent pool. The result is a
   rest-of-season value-over-replacement figure that drives waiver priority.

2. **Optimal FAAB bidding** — converts a free agent's ``ROS_DVORP`` into a
   recommended dollar bid, factoring in the user's remaining budget, the
   *user's* need at the position (does the upgrade replace a starter?), how
   many rivals still need the player, and how much FAAB those rivals retain.

The bidding model is intentionally closed-form and runs in ``O(n)`` per free
agent, well inside the <50ms per-event budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from engine.dvorp import compute_baselines
from engine.models import LeagueConfig, PlayerProjection, Position

# FAAB budgets default to a $100 budget (configurable per call).
DEFAULT_BUDGET: float = 100.0

# How strongly the rival competition term inflates a bid.
COMPETITION_WEIGHT: float = 0.6

# Converts a ROS_DVORP point directly into dollars before adjustments.
BID_SCALE: float = 1.0

# Floor bid in dollars; a player worth rostering is never suggested for $0.
MIN_BID: float = 1.0

# Season-long projections are prorated over this many regular-season weeks.
REGULAR_SEASON_WEEKS: int = 14


def ros_projection(projection: float, current_week: int) -> float:
    """Prorate a season-long projection to the remaining regular season.

    ``current_week`` is the NFL week *about to be played* (1-indexed and
    inclusive of the upcoming week). Past the end of the regular season the
    remaining projection collapses to zero.
    """
    if current_week > REGULAR_SEASON_WEEKS:
        return 0.0
    remaining = max(REGULAR_SEASON_WEEKS - current_week + 1, 0)
    return float(projection * remaining / REGULAR_SEASON_WEEKS)


def _prorated_copy(player: PlayerProjection, current_week: int) -> PlayerProjection:
    """Return a deep copy of ``player`` with a prorated projection."""
    p = player.model_copy(deep=True)
    p.fantasy_points = ros_projection(p.fantasy_points, current_week)
    return p


def compute_ros_dvorp(
    config: LeagueConfig,
    all_players: Sequence[PlayerProjection],
    *,
    current_week: int,
    available_ids: Optional[set[str]] = None,
) -> dict[str, float]:
    """Rest-of-season DVORP for every player in ``all_players``.

    The replacement baseline is computed over the *current* player pool
    (rostered players + free agents), prorated to the remaining schedule —
    mirroring :func:`engine.dvorp.compute_all_dvorp` for an in-season frame.
    ``available_ids`` optionally restricts which players are reported; the
    baselines still use the full pool.
    """
    by_position = [_prorated_copy(p, current_week) for p in all_players]
    baselines = compute_baselines(config, by_position, drafted_by_pos={})

    available = (
        available_ids
        if available_ids is not None
        else {p.player_id for p in all_players}
    )

    result: dict[str, float] = {}
    for p in by_position:
        if p.player_id not in available:
            continue
        result[p.player_id] = p.fantasy_points - baselines.get(p.position, 0.0)
    return result


def _need_factor(
    position: Position,
    roster_need: Optional[Mapping[Position, int]],
) -> float:
    """Convert explicit positional need into a bidding multiplier.

    ``roster_need`` maps position -> number of *starter* slots the user would
    upgrade by landing this player. A starter upgrade is worth full price; a
    bench flyer is damped.
    """
    need = roster_need or {}
    n = max(int(need.get(position, 0)), 0)
    return float(min(1.0 + 0.25 * n, 1.75)) if n > 0 else 0.6


@dataclass
class FaabBid:
    """Recommended FAAB bid for a single free agent."""

    player_id: str
    name: str
    position: Position
    ros_projection: float
    ros_dvorp: float
    replacement: float
    recommended_bid: float
    user_need_factor: float
    rival_pressure: float

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "position": self.position,
            "ros_projection": round(self.ros_projection, 2),
            "ros_dvorp": round(self.ros_dvorp, 2),
            "replacement": round(self.replacement, 2),
            "recommended_bid": round(self.recommended_bid, 2),
            "user_need_factor": round(self.user_need_factor, 3),
            "rival_pressure": round(self.rival_pressure, 3),
        }


def optimal_faab_bid(
    ros_dvorp: float,
    *,
    user_budget: float,
    user_need_factor: float = 1.0,
    rival_pressure: float = 0.0,
    teams_count: int = 12,
) -> float:
    """Optimal FAAB bid for one free agent.

    ``base = ros_dvorp * BID_SCALE``, damped by the share of the user's budget
    that commitment represents, boosted by rival competition (scaled by rival
    FAAB depth), and modulated by the user's own positional need::

        budget_damping = clamp(user_budget / DEFAULT_BUDGET, 0.1, 1.0)
        bid = base * budget_damping * (1 + COMPETITION_WEIGHT * rival_pressure)
              * user_need_factor

    A positive ROS_DVORP always yields at least ``MIN_BID``; a non-positive
    ROS_DVORP yields ``0.0`` (don't bid).
    """
    if ros_dvorp <= 0:
        return 0.0

    budget_damping = max(min(user_budget / DEFAULT_BUDGET, 1.0), 0.1)
    competition = 1.0 + COMPETITION_WEIGHT * rival_pressure
    bid = (
        ros_dvorp
        * BID_SCALE
        * budget_damping
        * competition
        * user_need_factor
    )
    return round(max(bid, MIN_BID), 2)


def calculate_faab_bids(
    config: LeagueConfig,
    free_agents: Sequence[PlayerProjection],
    all_players: Sequence[PlayerProjection],
    *,
    current_week: int,
    user_budget: float,
    roster_need: Optional[Mapping[Position, int]] = None,
    rival_need_by_pos: Optional[Mapping[Position, int]] = None,
    rival_faab: Optional[Sequence[float]] = None,
) -> list[FaabBid]:
    """Rank free agents and produce recommended FAAB bids.

    * ``free_agents``: claimable players.
    * ``all_players``: full inventory used for the replacement baseline.
    * ``rival_need_by_pos``: how many *rivals* still need each position.
    * ``rival_faab``: each rival's remaining FAAB; scales the competition term.
    """
    available_ids = {p.player_id for p in free_agents}
    dvorp = compute_ros_dvorp(
        config,
        all_players,
        current_week=current_week,
        available_ids=available_ids,
    )

    prorated = [_prorated_copy(p, current_week) for p in all_players]
    baselines = compute_baselines(config, prorated, drafted_by_pos={})

    by_id = {p.player_id: p for p in all_players}

    r_need = dict(rival_need_by_pos or {})
    r_faab = list(rival_faab) if rival_faab else []
    avg_rival_faab = (sum(r_faab) / len(r_faab)) if r_faab else DEFAULT_BUDGET
    faab_pressure = max(min(avg_rival_faab / DEFAULT_BUDGET, 1.0), 0.0)
    teams_field = max(config.teams_count - 1, 1)

    bids: list[FaabBid] = []
    for player in free_agents:
        ros_d = dvorp.get(player.player_id, 0.0)
        if ros_d <= 0:
            # Do not surface unworthy claims; keep the table actionable.
            continue

        need_factor = _need_factor(player.position, roster_need)
        rival_count = max(r_need.get(player.position, 0), 0)
        rival_pressure = (rival_count / teams_field) * faab_pressure

        bid = optimal_faab_bid(
            ros_d,
            user_budget=user_budget,
            user_need_factor=need_factor,
            rival_pressure=rival_pressure,
            teams_count=config.teams_count,
        )

        player_meta = by_id[player.player_id]
        bids.append(
            FaabBid(
                player_id=player.player_id,
                name=player_meta.name,
                position=player.position,
                ros_projection=ros_projection(
                    player_meta.fantasy_points, current_week
                ),
                ros_dvorp=ros_d,
                replacement=baselines.get(player.position, 0.0),
                recommended_bid=bid,
                user_need_factor=need_factor,
                rival_pressure=rival_pressure,
            )
        )

    bids.sort(key=lambda b: (b.recommended_bid, b.ros_dvorp), reverse=True)
    return bids


__all__ = [
    "DEFAULT_BUDGET",
    "FaabBid",
    "calculate_faab_bids",
    "compute_ros_dvorp",
    "optimal_faab_bid",
    "ros_projection",
]