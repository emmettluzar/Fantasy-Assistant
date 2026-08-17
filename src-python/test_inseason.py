"""Phase 5 in-season automation verification (offline, no network).

Exercises the three new subsystems against mock rosters:

1. ``inseason.waivers`` — ROS_DVORP + optimal FAAB bidding.
2. ``inseason.trades`` — trade delta utility + win-probability impact.
3. ``inseason.optimizer`` — MILP lineup solver with injury/weather penalties.

Run with the venv interpreter from the repo root:

    src-python\\venv\\Scripts\\python src-python\\test_inseason.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src-python")

from engine.models import LeagueConfig, PlayerProjection, RosterSettings

from inseason.optimizer import RosterPlayer, adjusted_projection, optimize_lineup
from inseason.trades import (
    evaluate_trade,
    roster_utility,
    season_adjusted_points,
    win_probability,
)
from inseason.waivers import (
    calculate_faab_bids,
    compute_ros_dvorp,
    optimal_faab_bid,
    ros_projection,
)


def make_player(
    pid: str,
    name: str,
    position: str,
    fantasy_points: float,
) -> PlayerProjection:
    return PlayerProjection(
        player_id=pid,
        name=name,
        position=position,
        fantasy_points=fantasy_points,
    )


def standard_config() -> LeagueConfig:
    """QB/RB/RB/WR/WR/TE/FLEX/K/DST with 12 teams."""
    return LeagueConfig(
        name="Test",
        teams_count=12,
        roster_slots=RosterSettings(
            QB=1, RB=2, WR=2, TE=1, FLEX=1, SUPERFLEX=0, K=1, DST=1
        ),
    )


def check(name: str, condition: bool, failures: list[str], detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    failures: list[str] = []

    print("=" * 78)
    print("Phase 5: in-season automation verification")
    print("=" * 78)

    # ------------------------------------------------------------------
    # 1. Waivers
    # ------------------------------------------------------------------
    print("\n[1] FAAB / waiver assistant")
    check(
        "ros_projection prorates remaining schedule",
        abs(ros_projection(140.0, current_week=8) - (140.0 * 7 / 14)) < 1e-6,
        failures,
    )
    check(
        "ros_projection collapses past week 14",
        ros_projection(140.0, current_week=15) == 0.0,
        failures,
    )

    config = standard_config()
    # Build a realistic 12-team player pool: projections descend steadily so the
    # replacement baseline (n-th best remaining at each position) sits in the
    # middle, leaving genuine value for above-replacement free agents.
    pool: list[PlayerProjection] = []
    for i in range(16):
        pool.append(make_player(f"QB{i}", f"QB {i}", "QB", 26.0 - i * 0.8))
    for i in range(30):
        pool.append(make_player(f"RBA{i}", f"RB {i}", "RB", 22.0 - i * 0.5))
    for i in range(40):
        pool.append(make_player(f"WRA{i}", f"WR {i}", "WR", 20.0 - i * 0.4))
    for i in range(16):
        pool.append(make_player(f"TEA{i}", f"TE {i}", "TE", 16.0 - i * 0.6))

    # Mid-tier free agents, all clearly above their positional replacement
    # baseline (RB ~7.5, WR ~8.0, TE ~8.2 for a 12-team full-flex league).
    free_agents = [
        make_player("FA-RB", "Free Agent RB", "RB", 17.0),
        make_player("FA-WR", "Free Agent WR", "WR", 16.0),
        make_player("FA-TE", "Free Agent TE", "TE", 12.4),
    ]
    all_players = pool + free_agents

    dvorp = compute_ros_dvorp(
        config,
        all_players,
        current_week=6,
        available_ids={p.player_id for p in free_agents},
    )
    check(
        "ROS_DVORP positive for above-replacement free agents",
        all(dvorp.get(p.player_id, 0.0) > 0 for p in free_agents),
        failures,
        str(dvorp),
    )

    bids = calculate_faab_bids(
        config,
        free_agents,
        all_players,
        current_week=6,
        user_budget=72,
        roster_need={"RB": 1, "WR": 1},
        rival_need_by_pos={"RB": 3, "WR": 2, "TE": 1},
        rival_faab=[80.0, 55.0, 91.0, 43.0, 67.0, 12.0, 74.0, 30.0, 88.0, 51.0, 22.0],
    )
    check("bids produced for positive-DVORP free agents", len(bids) == 3, failures, str(len(bids)))
    check(
        "free agent RB ranked first by bid",
        bids[0].player_id == "FA-RB",
        failures,
        str(bids[0].player_id),
    )
    by_id_faab = {b.player_id: b for b in bids}
    check(
        "higher-projection RB bids more than TE",
        by_id_faab["FA-RB"].recommended_bid > by_id_faab["FA-TE"].recommended_bid,
        failures,
        str({k: v.recommended_bid for k, v in by_id_faab.items()}),
    )
    broke = optimal_faab_bid(10.0, user_budget=10.0, user_need_factor=1.0, rival_pressure=0.0)
    flush = optimal_faab_bid(10.0, user_budget=100.0, user_need_factor=1.0, rival_pressure=0.0)
    check("budget damping reduces bids when low on FAAB", broke < flush, failures, f"{broke} < {flush}")
    check(
        "non-positive DVORP yields zero bid",
        optimal_faab_bid(-1.0, user_budget=100.0) == 0.0,
        failures,
    )

    # ------------------------------------------------------------------
    # 2. Trades
    # ------------------------------------------------------------------
    print("\n[2] Trade analyzer")
    user_roster = [
        make_player("QB1", "QB Allen", "QB", 24.1),
        make_player("RB1", "RB CMC", "RB", 21.8),
        make_player("RB2", "RB Henry", "RB", 19.2),
        make_player("RB4", "RB Pollard", "RB", 11.9),
        make_player("WR1", "WR Jefferson", "WR", 20.6),
        make_player("WR3", "WR Lamb", "WR", 18.1),
        make_player("TE1", "TE Kelce", "TE", 15.7),
    ]
    opponent_roster = [
        make_player("QB2", "QB Hurts", "QB", 22.4),
        make_player("RB3", "RB Walker", "RB", 13.5),
        make_player("WR2", "WR Chase", "WR", 19.4),
        make_player("WR4", "WR Hill", "WR", 15.2),
        make_player("TE2", "TE McBride", "TE", 12.3),
    ]

    pre = roster_utility(config, user_roster, current_week=6)
    post = roster_utility(
        config,
        [p for p in user_roster if p.player_id != "RB4"]
        + [make_player("WR2", "WR Chase", "WR", 19.4)],
        current_week=6,
    )
    check("acquiring a better flex player raises utility", post > pre, failures, f"{pre} -> {post}")

    evaluation = evaluate_trade(
        config,
        user_roster,
        opponent_roster,
        current_week=6,
        user_gives=["RB4"],
        user_receives=["WR2"],
    )
    check("trade delta utility is positive", evaluation.delta_utility > 0, failures, str(evaluation.delta_utility))
    check(
        "trade win probability improves",
        evaluation.delta_win_probability > 0,
        failures,
        str(evaluation.delta_win_probability),
    )
    check("trade recommended", evaluation.recommended is True, failures)
    check(
        "opponent delta utility is negative",
        evaluation.opponent_delta_utility < 0,
        failures,
        str(evaluation.opponent_delta_utility),
    )

    check(
        "season_adjusted_points weights playoffs",
        season_adjusted_points(140.0, current_week=14) > ros_projection(140.0, current_week=14),
        failures,
    )
    check(
        "win_probability is 0.5 at equal expected points",
        abs(win_probability(100.0, 100.0) - 0.5) < 1e-6,
        failures,
    )

    # ------------------------------------------------------------------
    # 3. MILP lineup optimizer
    # ------------------------------------------------------------------
    print("\n[3] MILP lineup optimizer")
    roster = [
        RosterPlayer("QB1", "QB Allen", "QB", 24.1),
        RosterPlayer("QB2", "QB Hurts", "QB", 22.4, injury_tag="Q"),
        RosterPlayer("RB1", "RB CMC", "RB", 21.8),
        RosterPlayer("RB2", "RB Henry", "RB", 19.2),
        RosterPlayer("RB3", "RB Walker", "RB", 13.5, weather="SNOW"),
        RosterPlayer("RB4", "RB Pollard", "RB", 11.9),
        RosterPlayer("WR1", "WR Jefferson", "WR", 20.6),
        RosterPlayer("WR2", "WR Chase", "WR", 19.4),
        RosterPlayer("WR3", "WR Lamb", "WR", 18.1),
        RosterPlayer("WR4", "WR Hill", "WR", 15.2, injury_tag="OUT"),
        RosterPlayer("TE1", "TE Kelce", "TE", 15.7),
        RosterPlayer("TE2", "TE McBride", "TE", 12.3),
        RosterPlayer("K1", "K Tucker", "K", 9.0),
        RosterPlayer("DST1", "DST Ravens", "DST", 8.5),
    ]
    result = optimize_lineup(config, roster)
    expected_starters = config.roster_slots.total_starters()
    check(
        "optimizer fills every starter slot",
        len(result.starters) == expected_starters,
        failures,
        f"{len(result.starters)} vs {expected_starters}",
    )
    starter_ids = {s.player_id for s in result.starters}
    check("OUT player never starts", "WR4" not in starter_ids, failures)
    check(
        "healthy QB starts over questionable QB",
        "QB1" in starter_ids and "QB2" not in starter_ids,
        failures,
        str(starter_ids),
    )
    check(
        "bench holds remaining players",
        len(result.bench) == len(roster) - expected_starters,
        failures,
        f"{len(result.bench)}",
    )
    check(
        "total projected is the sum of starters",
        abs(result.total_projected - sum(s.projected for s in result.starters)) < 1e-6,
        failures,
    )

    check(
        "OUT injury zeroes projection",
        adjusted_projection(20.0, injury_tag="OUT") == 0.0,
        failures,
    )
    check(
        "Questionable applies ~0.85 factor",
        abs(adjusted_projection(20.0, injury_tag="Q") - 20.0 * 0.85) < 1e-6,
        failures,
    )
    check(
        "snow penalty applies multiplicatively",
        abs(adjusted_projection(20.0, weather="SNOW") - 20.0 * 0.88) < 1e-6,
        failures,
    )

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    if failures:
        print(f"RESULT: FAIL ({len(failures)} failure(s))")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())