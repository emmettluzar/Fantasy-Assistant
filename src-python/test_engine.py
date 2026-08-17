"""Phase 1 engine acceptance test.

Simulates a live 12-team snake draft for two league configurations:

1. Standard PPR (full-PPR, default roster).
2. Custom 6-pt passing TD / Superflex league.

For each league the script:

* builds the projection pool (offline synthetic fallback),
* drafts each pick in snake order, where opponent picks are selected by the
  current best-available value (DVORP) and the user's picks are chosen by
  the master decision utility ``U_i(t)``,
* prints the top recommended pick at the user's turn.

Run with the packaged virtual environment::

    src-python\\venv\\Scripts\\python src-python\\test_engine.py
"""

from __future__ import annotations

import time
from collections import defaultdict

from engine.dvorp import compute_all_dvorp
from engine.models import (
    DraftPick,
    LeagueConfig,
    PlayerProjection,
    Position,
    ScoringRules,
)
from engine.probability import (
    DecisionContext,
    compute_player_dvorp_map,
    rank_decisions,
)
from engine.projections import build_projection_pool, filter_available

USER_TEAM_INDEX = 0
ROUNDS = 15


def compute_user_next_pick(current: int, teams: int) -> float:
    """Return the user's next pick strictly after ``current``.

    Pre-computed picks assume standard snake ordering; this computes it
    directly: user picks at positions ``p`` and ``(2*teams - p + 1)``.
    """
    later_user_picks = []
    p = USER_TEAM_INDEX + 1  # 1-based
    for rnd in range(1, ROUNDS + 1):
        if rnd % 2 == 1:
            pick = (rnd - 1) * teams + p
        else:
            pick = (rnd - 1) * teams + (teams - p + 1)
        if pick > current:
            later_user_picks.append(pick)
    return float(min(later_user_picks)) if later_user_picks else 0.0


def assign_bye_weeks(pool: list[PlayerProjection]) -> None:
    """Deterministic bye weeks so the bye-overlap penalty is exercised."""
    for p in pool:
        h = hash(p.player_id) % 10
        p.bye_week = 5 + h


def draft_scenario(config: LeagueConfig, title: str, seed: int = 7) -> None:
    print("\n" + "=" * 78)
    print(f"{title}")
    print("=" * 78)
    print(f"Scoring: pass_td={config.scoring.pass_td}, rec={config.scoring.rec}, "
          f"te_rec_bonus={config.scoring.te_rec_bonus}")
    print(f"Roster: QB={config.roster_slots.QB}, RB={config.roster_slots.RB}, "
          f"WR={config.roster_slots.WR}, TE={config.roster_slots.TE}, "
          f"FLEX={config.roster_slots.FLEX}, SUPERFLEX={config.roster_slots.SUPERFLEX}, "
          f"BENCH={config.roster_slots.BENCH}")
    print(f"Teams: {config.teams_count}")

    pool = build_projection_pool(config, allow_network=False, seed=seed)
    assign_bye_weeks(pool)

    by_id = {p.player_id: p for p in pool}

    drafted_ids: set[str] = set()
    drafted_positions: list[Position] = []
    picked: list[DraftPick] = []

    user_owned: dict[Position, int] = defaultdict(int)
    user_roster: list[PlayerProjection] = []
    user_starters_bye: dict[int, int] = defaultdict(int)

    teams = config.teams_count
    total_picks = teams * ROUNDS
    overall = 0
    timings: list[float] = []

    for rnd in range(1, ROUNDS + 1):
        ordering = list(range(teams))
        if rnd % 2 == 0:
            ordering.reverse()

        for team_index in ordering:
            overall += 1
            if overall > total_picks:
                break

            remaining = filter_available(pool, drafted_ids)
            if not remaining:
                continue

            # Count already-drafted players per position (all teams) so the
            # replacement baseline reflects the shrinking pool.
            drafted_by_pos = defaultdict(int)
            for pos in drafted_positions:
                drafted_by_pos[pos] += 1

            dvorp_results = compute_all_dvorp(config, remaining, dict(drafted_by_pos))
            dvorp_map = compute_player_dvorp_map(dvorp_results)

            t0 = time.perf_counter()
            if team_index == USER_TEAM_INDEX:
                r_next = compute_user_next_pick(overall, teams)
                context = DecisionContext(
                    dvorp=dvorp_map,
                    roster_slots=config.roster_slots,
                    owned=dict(user_owned),
                    starters_bye=dict(user_starters_bye),
                    r_next=r_next,
                )
                ranked = rank_decisions(remaining, context, dvorp_by_id=dvorp_map)
                choice = ranked[0] if ranked else None
                if choice is None:
                    continue
                player = by_id[choice.player_id]
                user_owned[player.position] += 1
                user_roster.append(player)
                if len(user_roster) <= config.roster_slots.total_starters():
                    user_starters_bye[player.bye_week] += 1

                print(
                    f"[Pick {overall:3d} | R{rnd:2d} | USER] "
                    f"Top rec: {player.name:20s} {player.position:2s} "
                    f"FP={player.fantasy_points:6.1f} DVORP={choice.dvorp:6.2f} "
                    f"P_MB={choice.p_mb:5.3f} R_need={choice.r_need:5.3f} "
                    f"P_bye={choice.p_bye:5.3f} Util={choice.utility:7.4f}"
                )
            else:
                # Opponent: draft best remaining value (pure DVORP).
                best = max(dvorp_results, key=lambda r: (r.dvorp, r.projection))
                player = by_id[best.player_id]

            # Record the pick.
            drafted_ids.add(player.player_id)
            drafted_positions.append(player.position)
            picked.append(
                DraftPick(
                    pick_number=overall,
                    round=rnd,
                    team_index=team_index,
                    player_id=player.player_id,
                    position=player.position,
                    fantasy_points=player.fantasy_points,
                )
            )
            dt = (time.perf_counter() - t0) * 1000.0
            timings.append(dt)

    avg_ms = sum(timings) / len(timings) if timings else 0.0
    max_ms = max(timings) if timings else 0.0
    print("-" * 78)
    print(f"User roster ({len(user_roster)} players):")
    for p in user_roster:
        print(f"  {p.name:20s} {p.position:2s} FP={p.fantasy_points:6.1f} BYE={p.bye_week}")
    print(f"Total picks simulated: {len(picked)}")
    print(f"DVORP/decision latency: avg={avg_ms:.2f}ms  max={max_ms:.2f}ms "
          f"(target < 50ms)")


def main() -> None:
    ppr = LeagueConfig.full_ppr()
    draft_scenario(ppr, "Scenario 1: Standard 12-team Full-PPR")

    custom = LeagueConfig(
        name="Custom 6pt Superflex",
        scoring=ScoringRules(pass_td=6.0, rec=1.0),
        roster_slots=LeagueConfig.superflex().roster_slots,
        teams_count=12,
    )
    draft_scenario(custom, "Scenario 2: Custom 6pt Pass-TD / Full-PPR Superflex")


if __name__ == "__main__":
    main()