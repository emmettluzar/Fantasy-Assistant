"""Dynamic Value Over Replacement Player (DVORP).

MATH_MODELS.md §3:

    DVORP_i(t) = E[FP_i] - E[FP_repl(p, t)]

where the replacement threshold is the projected fantasy points of the
*n*-th best remaining player at position ``p``:

    n(p) = teams_count * roster_slots[p] + flex_allocation

In Superflex configurations (``SUPERFLEX >= 1``) the QB replacement baseline
expands to ``teams_count * (roster_slots['QB'] + roster_slots['SUPERFLEX'])``.

Because the baseline is recomputed from *remaining* (undrafted) players after
each pick, DVORP tracks the value of the pickable pool as the draft
progresses rather than using a static preseason ranking.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .models import LeagueConfig, PlayerProjection, Position, SKILL_POSITIONS


@dataclass
class ReplacementBaseline:
    """DVORP replacement points for each position at a point in the draft."""

    baselines: dict[Position, float] = field(default_factory=dict)

    def get(self, position: Position, default: float = 0.0) -> float:
        return self.baselines.get(position, default)


@dataclass
class DvorpResult:
    """A player's DVORP along with the replacement baseline used."""

    player_id: str
    position: Position
    projection: float
    replacement: float
    dvorp: float

    @property
    def value(self) -> float:
        return self.dvorp


def _replacement_count(
    config: LeagueConfig, position: Position, *, drafted_by_pos: Mapping[Position, int]
) -> int:
    """League-wide number of *started* players to fill at ``position`` plus flex.

    This implements the MATH_MODELS.md baseline formulation, including the
    superflex expansion for quarterbacks. The count of already-drafted players
    is subtracted so the result is the number of *remaining* starters to fill.
    """
    slots = config.replacement_slots(position, include_flex=True)
    used = int(drafted_by_pos.get(position, 0))
    return max(int(round(slots)) - used, 0)


def compute_replacement_baseline(
    position: Position,
    remaining: Sequence[PlayerProjection],
    n: int,
) -> float:
    """Projected points of the ``n``-th best remaining player at ``position``.

    If fewer than ``n`` players remain, the baseline collapses to the lowest
    remaining projection (or 0.0 when the position is exhausted).
    """
    if n <= 0:
        return 0.0
    same_pos = [p for p in remaining if p.position == position]
    if not same_pos:
        return 0.0
    sorted_fp = sorted((p.fantasy_points for p in same_pos), reverse=True)
    if n > len(sorted_fp):
        return sorted_fp[-1]
    return sorted_fp[n - 1]


def compute_baselines(
    config: LeagueConfig,
    remaining: Sequence[PlayerProjection],
    drafted_by_pos: Optional[Mapping[Position, int]] = None,
    positions: Sequence[Position] = SKILL_POSITIONS,
) -> ReplacementBaseline:
    """Compute the replacement baseline for every skill position.

    ``remaining`` should be the currently undrafted player pool and
    ``drafted_by_pos`` the count of players already selected at each position.
    """
    drafted = dict(drafted_by_pos or {})
    baselines: dict[Position, float] = {}
    for position in positions:
        n = _replacement_count(config, position, drafted_by_pos=drafted)
        baselines[position] = compute_replacement_baseline(position, remaining, n)
    return ReplacementBaseline(baselines=baselines)


def compute_dvorp(
    player: PlayerProjection,
    baseline: float,
) -> float:
    """Per-player DVORP: projection minus the positional replacement baseline."""
    return float(player.fantasy_points - baseline)


def compute_all_dvorp(
    config: LeagueConfig,
    remaining: Sequence[PlayerProjection],
    drafted_by_pos: Optional[Mapping[Position, int]] = None,
) -> list[DvorpResult]:
    """Compute DVORP for every remaining player in one pass.

    This is the hot path called after each pick, so it is written to complete
    in well under 50ms for the expected pool sizes (< ~200 players).
    """
    drafted = dict(drafted_by_pos or {})
    baselines = compute_baselines(config, remaining, drafted_by_pos=drafted)
    results: list[DvorpResult] = []
    for p in remaining:
        baseline = baselines.get(p.position, 0.0)
        results.append(
            DvorpResult(
                player_id=p.player_id,
                position=p.position,
                projection=p.fantasy_points,
                replacement=baseline,
                dvorp=compute_dvorp(p, baseline),
            )
        )
    return results


def rank_by_dvorp(
    config: LeagueConfig,
    remaining: Sequence[PlayerProjection],
    drafted_by_pos: Optional[Mapping[Position, int]] = None,
) -> list[DvorpResult]:
    """Rank remaining players by DVORP (descending)."""
    results = compute_all_dvorp(config, remaining, drafted_by_pos)
    results.sort(key=lambda r: (r.dvorp, r.projection), reverse=True)
    return results


def count_drafted_by_pos(
    drafted_positions: Sequence[Position],
) -> dict[Position, int]:
    """Tally drafted players per position."""
    counts: dict[Position, int] = defaultdict(int)
    for position in drafted_positions:
        if position in SKILL_POSITIONS:
            counts[position] += 1
    return dict(counts)


__all__ = [
    "ReplacementBaseline",
    "DvorpResult",
    "compute_replacement_baseline",
    "compute_baselines",
    "compute_dvorp",
    "compute_all_dvorp",
    "rank_by_dvorp",
    "count_drafted_by_pos",
]