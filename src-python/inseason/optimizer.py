"""MILP lineup optimizer (Phase 5).

Solves the weekly start/sit decision as a Mixed Integer Linear Program:

    maximize  sum_i  adjusted_projection(i) * x_i
    subject to roster slot constraints (QB/RB/WR/TE/FLEX/SUPERFLEX/K/DST)

The solver uses :mod:`pydfs_lineup_optimizer` (a PuLP-backed MILP engine) as
the primary backend per the Phase 5 spec. Because that library is DFS-oriented,
it is wrapped in a validation + fallback path: if the pydfs import/solve fails
or returns an invalid lineup, a hand-rolled PuLP MILP is used instead (PuLP
ships in the same venv). Both backends maximize the same objective over the
same :class:`~engine.models.LeagueConfig` roster constraints.

Dynamic penalty factors:

* Injury tags (``Q``, ``D``, ``OUT``/``IR``) reduce or zero a player's expected
  points.
* Weather conditions (snow, heavy rain, high wind, cold, ...) apply an
  additional multiplicative penalty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from engine.models import LeagueConfig, Position

# Multiplicative factors applied for each injury designation.
INJURY_FACTORS: dict[str, float] = {
    "OUT": 0.0,
    "IR": 0.0,
    "D": 0.40,
    "Q": 0.85,
}

# Multiplicative factors applied for adverse weather.
WEATHER_FACTORS: dict[str, float] = {
    "SNOW": 0.88,
    "STORM": 0.88,
    "HEAVY_RAIN": 0.90,
    "HIGH_WIND": 0.90,
    "RAIN": 0.95,
    "WIND": 0.95,
    "COLD": 0.95,
}

FLEX_ELIGIBLE: tuple[Position, ...] = ("RB", "WR", "TE")
SUPERFLEX_ELIGIBLE: tuple[Position, ...] = ("QB", "RB", "WR", "TE")
DEDICATED_POSITIONS: tuple[Position, ...] = ("QB", "RB", "WR", "TE", "K", "DST")


def adjusted_projection(
    fantasy_points: float,
    *,
    injury_tag: Optional[str] = None,
    weather: Optional[str] = None,
) -> float:
    """Expected fantasy points after injury and weather penalties.

    Both penalties are multiplicative and compose. An OUT/IR player is forced
    to zero regardless of weather.
    """
    fp = float(fantasy_points)

    tag = (injury_tag or "").strip().upper()
    factor = INJURY_FACTORS.get(tag, 1.0)
    if factor == 0.0:
        return 0.0
    fp *= factor

    condition = (weather or "").strip().upper()
    fp *= WEATHER_FACTORS.get(condition, 1.0)

    return float(fp)


@dataclass
class RosterPlayer:
    """A player on the active roster with weekly context."""

    player_id: str
    name: str
    position: Position
    fantasy_points: float
    team: str = ""
    injury_tag: Optional[str] = None
    weather: Optional[str] = None
    ceiling: Optional[float] = None
    floor: Optional[float] = None

    def adjusted(self) -> float:
        return adjusted_projection(
            self.fantasy_points,
            injury_tag=self.injury_tag,
            weather=self.weather,
        )

    def resolved_ceiling(self, projected: float) -> float:
        return self.ceiling if self.ceiling is not None else projected * 1.10

    def resolved_floor(self, projected: float) -> float:
        return self.floor if self.floor is not None else projected * 0.90


@dataclass
class LineupSlot:
    """A single resolved roster slot (starter or bench)."""

    slot: str
    player_id: str
    name: str
    position: Position
    projected: float
    ceiling: float
    floor: float
    injury_tag: Optional[str] = None
    weather: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "player_id": self.player_id,
            "name": self.name,
            "position": self.position,
            "projected": round(self.projected, 2),
            "ceiling": round(self.ceiling, 2),
            "floor": round(self.floor, 2),
            "injury_tag": self.injury_tag,
            "weather": self.weather,
        }


@dataclass
class LineupOptimization:
    """Full optimized lineup plus bench."""

    starters: list[LineupSlot]
    bench: list[LineupSlot]
    total_projected: float
    total_ceiling: float
    total_floor: float
    solver_used: str

    def to_dict(self) -> dict:
        return {
            "starters": [s.to_dict() for s in self.starters],
            "bench": [s.to_dict() for s in self.bench],
            "total_projected": round(self.total_projected, 2),
            "total_ceiling": round(self.total_ceiling, 2),
            "total_floor": round(self.total_floor, 2),
            "solver_used": self.solver_used,
        }


# ---------------------------------------------------------------------------
# PuLP MILP backend (guaranteed fallback)
# ---------------------------------------------------------------------------
#
# One binary variable per (player, role) pair, created *only* for roles that
# actually exist in the league's roster settings. This avoids the classic bug
# of an unconstrained "flex"/"superflex" bin soaking up every spare player.


def _solve_with_pulp(
    config: LeagueConfig,
    players: Sequence[RosterPlayer],
    adjusted: dict[str, float],
) -> LineupOptimization:
    import pulp  # local import keeps the module import-light

    slots = config.roster_slots
    ids = [p.player_id for p in players]
    by_id = {p.player_id: p for p in players}

    prob = pulp.LpProblem("weekly_lineup", pulp.LpMaximize)

    # (player_id, role) -> LpVariable; only roles in play are created.
    vars_by_role: dict[tuple[str, str], pulp.LpVariable] = {}

    def role_var(pid: str, role: str) -> pulp.LpVariable:
        key = (pid, role)
        if key not in vars_by_role:
            vars_by_role[key] = pulp.LpVariable(f"{role}_{pid}", cat="Binary")
        return vars_by_role[key]

    # Dedicated positions.
    for pos in DEDICATED_POSITIONS:
        count = getattr(slots, pos, 0)
        if count <= 0:
            continue
        pos_ids = [pid for pid in ids if by_id[pid].position == pos]
        if not pos_ids:
            continue
        x = [role_var(pid, pos) for pid in pos_ids]
        prob += pulp.lpSum(x) == min(count, len(pos_ids))

    # Flex (RB/WR/TE).
    if slots.FLEX:
        flex_ids = [pid for pid in ids if by_id[pid].position in FLEX_ELIGIBLE]
        if flex_ids:
            x = [role_var(pid, "FLEX") for pid in flex_ids]
            prob += pulp.lpSum(x) == min(slots.FLEX, len(flex_ids))

    # Superflex (QB/RB/WR/TE).
    if slots.SUPERFLEX:
        sflx_ids = [pid for pid in ids if by_id[pid].position in SUPERFLEX_ELIGIBLE]
        if sflx_ids:
            x = [role_var(pid, "SUPERFLEX") for pid in sflx_ids]
            prob += pulp.lpSum(x) == min(slots.SUPERFLEX, len(sflx_ids))

    # Objective: maximize adjusted points across every chosen role.
    prob += pulp.lpSum(adjusted[pid] * var for (pid, _role), var in vars_by_role.items())

    # Each player may occupy at most one role.
    per_player: dict[str, list[pulp.LpVariable]] = {}
    for (pid, _role), var in vars_by_role.items():
        per_player.setdefault(pid, []).append(var)
    for pid, vars_list in per_player.items():
        if len(vars_list) > 1:
            prob += pulp.lpSum(vars_list) <= 1

    status = prob.solve()
    if status != pulp.LpStatusOptimal:
        raise RuntimeError(f"PuLP lineup solve failed: {pulp.LpStatus[prob.status]}")

    selected: dict[str, str] = {}
    for (pid, role), var in vars_by_role.items():
        if pulp.value(var) is not None and pulp.value(var) > 0.5:
            selected[pid] = role

    return _build_result(config, players, adjusted, selected, solver="pulp")


# ---------------------------------------------------------------------------
# pydfs-lineup-optimizer backend (primary, with validation)
# ---------------------------------------------------------------------------


def _solve_with_pydfs(
    config: LeagueConfig,
    players: Sequence[RosterPlayer],
    adjusted: dict[str, float],
) -> LineupOptimization:
    from pydfs_lineup_optimizer import LineupOptimizer, Player
    from pydfs_lineup_optimizer.settings import BaseSettings, LineupPosition

    slots = config.roster_slots

    positions: list[LineupPosition] = []
    for _ in range(slots.QB):
        positions.append(LineupPosition("QB", ("QB",)))
    for _ in range(slots.RB):
        positions.append(LineupPosition("RB", ("RB",)))
    for _ in range(slots.WR):
        positions.append(LineupPosition("WR", ("WR",)))
    for _ in range(slots.TE):
        positions.append(LineupPosition("TE", ("TE",)))
    for _ in range(slots.K):
        positions.append(LineupPosition("K", ("K",)))
    for _ in range(slots.DST):
        positions.append(LineupPosition("DST", ("DST",)))
    for _ in range(slots.FLEX):
        positions.append(LineupPosition("FLEX", FLEX_ELIGIBLE))
    for _ in range(slots.SUPERFLEX):
        positions.append(LineupPosition("SUPERFLEX", SUPERFLEX_ELIGIBLE))

    class _SeasonSettings(BaseSettings):
        budget = 1_000_000_000
        max_from_one_team = None
        min_from_one_team = None

    _SeasonSettings.positions = positions

    optimizer = LineupOptimizer(_SeasonSettings)
    for p in players:
        optimizer.add_player_to_optimizer(
            Player(
                p.player_id,
                p.name,
                "",
                [p.position],
                p.team or "TM",
                0,
                fppg=adjusted[p.player_id],
            )
        )

    lineups = optimizer.optimize(1)
    if not lineups:
        raise RuntimeError("pydfs returned no lineup")

    best = lineups[0]
    extracted = getattr(best, "lineup", None)
    selected: dict[str, str] = {}
    if extracted:
        for entry in extracted:
            player = entry[0]
            slot_meta = entry[1]
            slot_name = getattr(slot_meta, "name", None) or str(slot_meta)
            selected[str(getattr(player, "id"))] = slot_name
    else:
        for player in best.players:
            pid = str(getattr(player, "id"))
            pos = getattr(player, "positions", ["RB"])[0]
            selected[pid] = pos

    expected_starters = config.roster_slots.total_starters()
    if len(selected) != expected_starters:
        raise RuntimeError(
            f"pydfs lineup size {len(selected)} != {expected_starters}"
        )

    return _build_result(config, players, adjusted, selected, solver="pydfs")


# ---------------------------------------------------------------------------
# Shared result assembly
# ---------------------------------------------------------------------------


def _build_result(
    config: LeagueConfig,
    players: Sequence[RosterPlayer],
    adjusted: dict[str, float],
    selected: dict[str, str],
    *,
    solver: str,
) -> LineupOptimization:
    by_id = {p.player_id: p for p in players}
    selected_ids = set(selected.keys())

    starters: list[LineupSlot] = []

    for pos in DEDICATED_POSITIONS:
        pos_slots = sorted(
            (pid for pid, role in selected.items() if role == pos),
            key=lambda pid: -adjusted[pid],
        )
        for index, pid in enumerate(pos_slots):
            starters.append(_slot(by_id[pid], f"{pos}{index + 1}", adjusted[pid]))

    flex_slots = sorted(
        (pid for pid, role in selected.items() if role == "FLEX"),
        key=lambda pid: -adjusted[pid],
    )
    for index, pid in enumerate(flex_slots):
        starters.append(_slot(by_id[pid], f"FLEX{index + 1}", adjusted[pid]))

    sflx_slots = sorted(
        (pid for pid, role in selected.items() if role == "SUPERFLEX"),
        key=lambda pid: -adjusted[pid],
    )
    for index, pid in enumerate(sflx_slots):
        starters.append(_slot(by_id[pid], f"SUPERFLEX{index + 1}", adjusted[pid]))

    bench = [
        _slot(p, "BENCH", adjusted[p.player_id])
        for p in players
        if p.player_id not in selected_ids
    ]
    bench.sort(key=lambda s: -s.projected)

    total_projected = sum(s.projected for s in starters)
    total_ceiling = sum(s.ceiling for s in starters)
    total_floor = sum(s.floor for s in starters)

    return LineupOptimization(
        starters=starters,
        bench=bench,
        total_projected=total_projected,
        total_ceiling=total_ceiling,
        total_floor=total_floor,
        solver_used=solver,
    )


def _slot(player: RosterPlayer, slot: str, projected: float) -> LineupSlot:
    return LineupSlot(
        slot=slot,
        player_id=player.player_id,
        name=player.name,
        position=player.position,
        projected=projected,
        ceiling=player.resolved_ceiling(projected),
        floor=player.resolved_floor(projected),
        injury_tag=player.injury_tag,
        weather=player.weather,
    )


def optimize_lineup(
    config: LeagueConfig,
    roster: Sequence[RosterPlayer],
) -> LineupOptimization:
    """Optimize the weekly starting lineup.

    Attempts the pydfs-lineup-optimizer MILP backend first; falls back to the
    hand-rolled PuLP MILP on any failure so a live draft never blocks on a
    library incompatibility.
    """
    adjusted = {p.player_id: p.adjusted() for p in roster}

    try:
        return _solve_with_pydfs(config, list(roster), adjusted)
    except Exception:
        return _solve_with_pulp(config, list(roster), adjusted)


__all__ = [
    "LineupOptimization",
    "LineupSlot",
    "RosterPlayer",
    "adjusted_projection",
    "optimize_lineup",
]