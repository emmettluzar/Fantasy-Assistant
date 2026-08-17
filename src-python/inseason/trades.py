"""Trade Analyzer engine (Phase 5).

Computes the change in a team's rest-of-season + playoff expected utility when
players are exchanged, surfacing the *delta utility* and the impact on the
user's estimated win probability.

The core model:

* ``roster_utility`` — prorate each rostered player's projection to the
  remaining regular-season weeks *and* playoff weeks (15–17, weighted
  separately), then pick the optimal starters for each slot via a greedy
  best-available assignment. The resulting points estimate is the roster's
  expected output.

* ``evaluate_trade`` — scores the roster before and after a proposed swap and
  returns the delta, plus win-probability impact estimated from a normal
  distribution over weekly scoring variance.

All helpers are ``O(n log n)`` in roster size and consume the shared
:class:`~engine.models.LeagueConfig` so custom scoring is respected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from scipy.stats import norm

from engine.models import LeagueConfig, PlayerProjection, Position

# Playoff weeks where the season is on the line (weeks 15, 16, 17).
PLAYOFF_WEEKS: tuple[int, ...] = (15, 16, 17)

# Relative importance of a playoff week vs a regular-season week.
PLAYOFF_WEIGHT: float = 1.5

# Regular-season span used for prorating season-long projections.
REGULAR_WEEKS: int = 14

# Std-dev (in weekly fantasy points) used for the win-probability model.
DEFAULT_WEEKLY_STD: float = 25.0


def season_adjusted_points(
    projection: float,
    *,
    current_week: int,
    playoff_weight: float = PLAYOFF_WEIGHT,
) -> float:
    """Weighted remaining schedule points for a season-long projection.

    Regular-season weeks are prorated ``(REGULAR_WEEKS - current_week + 1)``
    and each playoff week (15-17) contributes ``projection / REGULAR_WEEKS``
    points multiplied by ``playoff_weight`` (playoff weeks matter more).
    """
    if current_week > REGULAR_WEEKS:
        reg = 0.0
    else:
        reg = projection * (REGULAR_WEEKS - current_week + 1) / REGULAR_WEEKS

    per_week = projection / REGULAR_WEEKS
    playoff = sum(per_week * playoff_weight for _ in PLAYOFF_WEEKS)
    return float(reg + playoff)


def _starter_candidates(
    roster: Sequence[PlayerProjection],
    current_week: int,
) -> dict[Position, list[tuple[float, PlayerProjection]]]:
    """Group a roster by position with season-adjusted point values."""
    by_pos: dict[Position, list[tuple[float, PlayerProjection]]] = {}
    for p in roster:
        value = season_adjusted_points(p.fantasy_points, current_week=current_week)
        by_pos.setdefault(p.position, []).append((value, p))
    for pos in by_pos:
        by_pos[pos].sort(key=lambda t: t[0], reverse=True)
    return by_pos


def roster_utility(
    config: LeagueConfig,
    roster: Sequence[PlayerProjection],
    *,
    current_week: int,
) -> float:
    """Expected rest-of-season + playoff points for the best possible lineup.

    Fills dedicated positions first (QB/RB/WR/TE) with the best available
    player at each position, then flex slots with the best remaining
    RB/WR/TE. Returns a single cumulative expected-points figure.
    """
    slots = config.roster_slots
    by_pos = _starter_candidates(roster, current_week)

    def take(pos: Position, count: int) -> float:
        total = 0.0
        for _ in range(count):
            if not by_pos.get(pos):
                break
            value, _player = by_pos[pos].pop(0)
            total += value
        return total

    total = 0.0
    total += take("QB", slots.QB)
    total += take("RB", slots.RB)
    total += take("WR", slots.WR)
    total += take("TE", slots.TE)

    # Flex: best remaining RB/WR/TE.
    flex_pool: list[tuple[float, PlayerProjection]] = []
    for pos in ("RB", "WR", "TE"):
        flex_pool.extend(by_pos.get(pos, []))
    flex_pool.sort(key=lambda t: t[0], reverse=True)
    for _ in range(slots.FLEX + slots.SUPERFLEX):
        if not flex_pool:
            break
        value, _player = flex_pool.pop(0)
        total += value

    return float(total)


def win_probability(
    expected_points: float,
    opponent_expected: float,
    *,
    weekly_std: float = DEFAULT_WEEKLY_STD,
) -> float:
    """Probability the team outscores its opponent, modeled by a normal CDF.

    ``P(win) = Phi((expected - opponent_expected) / (sqrt(2) * weekly_std))``
    so a tie in expected points yields a 50/50 win probability.
    """
    if weekly_std <= 0:
        weekly_std = DEFAULT_WEEKLY_STD
    z = (expected_points - opponent_expected) / (2 ** 0.5 * weekly_std)
    return float(norm.cdf(z))


@dataclass
class TradeEvaluation:
    """Full result of a proposed trade."""

    pre_trade_utility: float
    post_trade_utility: float
    delta_utility: float
    pre_win_probability: float
    post_win_probability: float
    delta_win_probability: float
    opponent_pre_utility: float
    opponent_post_utility: float
    opponent_delta_utility: float
    recommended: bool

    def to_dict(self) -> dict:
        return {
            "pre_trade_utility": round(self.pre_trade_utility, 2),
            "post_trade_utility": round(self.post_trade_utility, 2),
            "delta_utility": round(self.delta_utility, 2),
            "pre_win_probability": round(self.pre_win_probability, 4),
            "post_win_probability": round(self.post_win_probability, 4),
            "delta_win_probability": round(self.delta_win_probability, 4),
            "opponent_pre_utility": round(self.opponent_pre_utility, 2),
            "opponent_post_utility": round(self.opponent_post_utility, 2),
            "opponent_delta_utility": round(self.opponent_delta_utility, 2),
            "recommended": self.recommended,
        }


def evaluate_trade(
    config: LeagueConfig,
    user_roster: Sequence[PlayerProjection],
    opponent_roster: Sequence[PlayerProjection],
    *,
    current_week: int,
    user_gives: Sequence[str],
    user_receives: Sequence[str],
    opponent_expected_points: Optional[float] = None,
    weekly_std: float = DEFAULT_WEEKLY_STD,
) -> TradeEvaluation:
    """Evaluate a trade between the user and an opponent.

    * ``user_roster`` / ``opponent_roster``: current rosters.
    * ``user_gives``: player ids the user is sending away.
    * ``user_receives``: player ids the user is acquiring.
    * ``opponent_expected_points``: optional opponent weekly total used for the
      win-probability reference; defaults to opponent's pre-trade utility.

    Returns a :class:`TradeEvaluation` with delta-utility for both sides and
    win-probability impact for the user.
    """
    user_by_id = {p.player_id: p for p in user_roster}
    opp_by_id = {p.player_id: p for p in opponent_roster}

    gives = [user_by_id[pid] for pid in user_gives if pid in user_by_id]
    receives = [opp_by_id[pid] for pid in user_receives if pid in opp_by_id]
    give_ids = set(user_gives)
    receive_ids = set(user_receives)

    pre_user = roster_utility(config, user_roster, current_week=current_week)
    pre_opp = roster_utility(config, opponent_roster, current_week=current_week)

    post_user = [p for p in user_roster if p.player_id not in give_ids]
    post_user.extend(receives)
    post_opp = [p for p in opponent_roster if p.player_id not in receive_ids]
    post_opp.extend(gives)

    post_user_utility = roster_utility(config, post_user, current_week=current_week)
    post_opp_utility = roster_utility(config, post_opp, current_week=current_week)

    delta_user = post_user_utility - pre_user
    delta_opp = post_opp_utility - pre_opp

    remaining_weight = max(
        (REGULAR_WEEKS - current_week + 1) + PLAYOFF_WEIGHT * len(PLAYOFF_WEEKS),
        1.0,
    )
    if opponent_expected_points is None:
        opponent_expected_points = pre_opp / remaining_weight

    pre_win = win_probability(
        pre_user / remaining_weight,
        opponent_expected_points,
        weekly_std=weekly_std,
    )
    post_win = win_probability(
        post_user_utility / remaining_weight,
        opponent_expected_points,
        weekly_std=weekly_std,
    )

    return TradeEvaluation(
        pre_trade_utility=pre_user,
        post_trade_utility=post_user_utility,
        delta_utility=delta_user,
        pre_win_probability=pre_win,
        post_win_probability=post_win,
        delta_win_probability=post_win - pre_win,
        opponent_pre_utility=pre_opp,
        opponent_post_utility=post_opp_utility,
        opponent_delta_utility=delta_opp,
        recommended=delta_user > 0,
    )


__all__ = [
    "PLAYOFF_WEEKS",
    "TradeEvaluation",
    "evaluate_trade",
    "roster_utility",
    "season_adjusted_points",
    "win_probability",
]