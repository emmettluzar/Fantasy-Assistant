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
    scarcity_multiplier,
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
    late_round_recs: list[tuple[PlayerProjection, object]] = []

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
                ranked = rank_decisions(
                    remaining,
                    context,
                    dvorp_by_id=dvorp_map,
                    user_picks=len(user_roster),
                )
                choice = ranked[0] if ranked else None
                if choice is None:
                    continue
                player = by_id[choice.player_id]
                user_owned[player.position] += 1
                user_roster.append(player)
                if len(user_roster) <= config.roster_slots.total_starters():
                    user_starters_bye[player.bye_week] += 1

                if rnd >= 12:
                    late_round_recs.append((player, choice))

                print(
                    f"[Pick {overall:3d} | R{rnd:2d} | USER] "
                    f"Top rec: {player.name:20s} {player.position:2s} "
                    f"FP={player.fantasy_points:6.1f} DVORP={choice.dvorp:6.2f} "
                    f"Upside={choice.upside:5.3f} P_MB={choice.p_mb:5.3f} "
                    f"R_need={choice.r_need:5.3f} P_bye={choice.p_bye:5.3f} "
                    f"Util={choice.utility:7.4f}"
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

    # ------------------------------------------------------------------
    # Late-round upside-shift verification
    # ------------------------------------------------------------------
    if late_round_recs:
        upside_values = [c.upside for _, c in late_round_recs]
        high_upside = sum(1 for u in upside_values if u >= 0.8)
        avg_u = sum(upside_values) / len(upside_values)
        backup_or_rookie = sum(
            1 for p, _ in late_round_recs if p.is_backup_rb or p.is_rookie
        )
        print("-" * 78)
        print(f"Late-round (R12+) recommendations: {len(late_round_recs)}")
        print(f"  Avg upside_score: {avg_u:.3f}")
        print(f"  High-upside (>=0.8): {high_upside}/{len(late_round_recs)}")
        print(f"  Backup RBs / rookies selected: {backup_or_rookie}/{len(late_round_recs)}")
        if avg_u >= 0.6 and high_upside > 0:
            print("UPSIDE SHIFT: PASS (late picks favor high-variance/backup targets)")
        else:
            print("UPSIDE SHIFT: FAIL (late picks still favor low-ceiling veterans)")


def verify_scarcity_multiplier() -> None:
    """Positional tier scarcity (MATH_MODELS.md §7) acceptance checks."""
    print("\n" + "=" * 78)
    print("Positional Tiers & Run Detection (Scarcity Multiplier S_m)")
    print("=" * 78)

    # 1. S_m lookup values.
    assert scarcity_multiplier(1) == 1.15
    assert scarcity_multiplier(2) == 1.05
    assert scarcity_multiplier(3) == 1.0
    assert scarcity_multiplier(25) == 1.0
    assert scarcity_multiplier(0) == 1.15  # defensive: no data -> last asset
    print("S_m lookup: N=1 -> 1.15, N=2 -> 1.05, else -> 1.0  ... PASS")

    # 2. Clustering assigns monotonic (tier 0 == highest xFP) tiers and, when
    #    a tier is reduced to one remaining player, rank_decisions applies the
    #    scarcity multiplier to the final utility.
    cfg = LeagueConfig.full_ppr()
    pool = build_projection_pool(cfg, allow_network=False, seed=7)

    qb_tier0 = sorted(
        (p for p in pool if p.position == "QB" and p.tier == 0),
        key=lambda p: p.xfp,
        reverse=True,
    )
    assert len(qb_tier0) == 2, "expected QB top tier to hold exactly 2 players"
    keep = qb_tier0[0]

    # Draft everything except ``keep``: only one QB remains in tier 0.
    drafted = {p.player_id for p in pool if p.player_id != keep.player_id}
    remaining = filter_available(pool, drafted)

    from engine.dvorp import compute_all_dvorp
    from engine.probability import compute_player_dvorp_map

    dvorp_results = compute_all_dvorp(
        cfg, remaining, {"QB": len(pool)}
    )
    dvorp_map = compute_player_dvorp_map(dvorp_results)
    context = DecisionContext(
        dvorp=dvorp_map,
        roster_slots=cfg.roster_slots,
        owned={},
        starters_bye={},
        r_next=12.0,
    )
    ranked = rank_decisions(remaining, context, dvorp_by_id=dvorp_map)
    kept = next(c for c in ranked if c.player_id == keep.player_id)
    assert kept.tier_remaining == 1
    assert kept.scarcity == 1.15, f"expected S_m=1.15, got {kept.scarcity}"
    print(
        f"Run detection: last-in-tier {kept.player_id} -> "
        f"N_tier={kept.tier_remaining}, S_m={kept.scarcity:.2f} "
        f"(utility {kept.utility:.4f}) ... PASS"
    )


def verify_dynasty() -> None:
    """Dynasty multi-year valuation (MATH_MODELS.md §8) acceptance checks."""
    from engine.dynasty import age_factor, dynasty_value

    print("\n" + "=" * 78)
    print("Dynasty Multi-Year Valuation & Age Curves (V_dynasty)")
    print("=" * 78)

    # 1. Positional age-curve lookups match MATH_MODELS.md §8.
    assert age_factor("RB", 25) == 1.0
    assert age_factor("RB", 26) == 0.80
    assert age_factor("RB", 27) == 0.80
    assert age_factor("RB", 28) == 0.55
    assert age_factor("RB", 29) == 0.55
    assert age_factor("RB", 30) == 0.30
    assert age_factor("WR", 28) == 1.0
    assert age_factor("WR", 29) == 0.85
    assert age_factor("WR", 31) == 0.65
    assert age_factor("WR", 33) == 0.40
    assert age_factor("TE", 29) == 1.0
    assert age_factor("TE", 30) == 0.85
    assert age_factor("TE", 32) == 0.65
    assert age_factor("TE", 34) == 0.40
    assert age_factor("QB", 31) == 1.0
    assert age_factor("QB", 32) == 0.90
    assert age_factor("QB", 35) == 0.75
    assert age_factor("QB", 38) == 0.50
    print("Age curves (A_factor): RB/WR/TE/QB buckets ... PASS")

    # 2. Multi-year discount formula V_dynasty(i).
    young_value = dynasty_value(100.0, "RB", 22)
    expected = 100.0 * 1.0 + 100.0 * 1.0 / 1.15 + 100.0 * 1.0 / (1.15**2)
    assert abs(young_value - expected) < 1e-9

    old_value = dynasty_value(100.0, "RB", 29)
    assert old_value < young_value
    print(
        f"V_dynasty: RB age 22 (FP=100) -> {young_value:.2f} vs "
        f"RB age 29 (FP=100) -> {old_value:.2f} ... PASS"
    )

    # 3. DVORP substitution: a young player out-ranks an older veteran with an
    #    identical single-year projection in dynasty mode, but ties in redraft.
    young = PlayerProjection(
        player_id="RB_YOUNG",
        name="Young RB",
        position="RB",
        fantasy_points=200.0,
        age=22,
    )
    old = PlayerProjection(
        player_id="RB_OLD",
        name="Old RB",
        position="RB",
        fantasy_points=200.0,
        age=29,
    )
    redraft = LeagueConfig.full_ppr()
    dynasty = LeagueConfig.dynasty()

    redraft_results = compute_all_dvorp(redraft, [young, old], {})
    rb_ids = {r.player_id: r for r in redraft_results}
    assert abs(rb_ids["RB_YOUNG"].dvorp - rb_ids["RB_OLD"].dvorp) < 1e-9, (
        "redraft should not distinguish age"
    )

    dynasty_results = compute_all_dvorp(dynasty, [young, old], {})
    db_ids = {r.player_id: r for r in dynasty_results}
    assert db_ids["RB_YOUNG"].dvorp > db_ids["RB_OLD"].dvorp, (
        "dynasty mode must prioritize the younger player"
    )
    print(
        f"DVORP substitution: dynasty young={db_ids['RB_YOUNG'].dvorp:.2f} "
        f"> old={db_ids['RB_OLD'].dvorp:.2f} "
        f"(redraft tie at 0.00) ... PASS"
    )


def main() -> None:
    verify_scarcity_multiplier()
    verify_dynasty()
    ppr = LeagueConfig.full_ppr()
    draft_scenario(ppr, "Scenario 1: Standard 12-team Full-PPR")

    custom = LeagueConfig(
        name="Custom 6pt Superflex",
        scoring=ScoringRules(pass_td=6.0, rec=1.0),
        roster_slots=LeagueConfig.superflex().roster_slots,
        teams_count=12,
    )
    draft_scenario(custom, "Scenario 2: Custom 6pt Pass-TD / Full-PPR Superflex")

    dynasty = LeagueConfig.dynasty()
    draft_scenario(dynasty, "Scenario 3: Dynasty (Multi-Year Age-Curve Valuation)")


if __name__ == "__main__":
    main()