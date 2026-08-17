"""Baseline projections pipeline.

This module converts raw player statistics (from ``nfl_data_py`` or a
deterministic synthetic fallback) into enriched :class:`PlayerProjection`
records containing the derived metrics defined in MATH_MODELS.md:

* xFP  -- expected fantasy points from opportunity/usage
* WOPR -- weighted opportunity rating
* EPA  -- estimated EPA per play
* CPOE -- completion percentage over expected
* fantasy_points -- projected points under the active scoring rules

All scoring-sensitive formulas read multipliers directly from the active
:class:`~engine.models.ScoringRules`, so the same projections can be
re-scored for any league format without touching this module's math.
"""

from __future__ import annotations

import logging
import random
from typing import Optional, Sequence

import pandas as pd

from .models import (
    LeagueConfig,
    PlayerProjection,
    Position,
    ScoringRules,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Derived-metric formulas (position-independent where possible)
# ---------------------------------------------------------------------------


def compute_fantasy_points(proj: PlayerProjection, scoring: ScoringRules) -> float:
    """Projected fantasy points from raw volume using ``scoring`` multipliers.

    This is the authoritative application of a user's custom scoring rules.
    """
    points = 0.0
    # Passing
    points += proj.pass_yards * scoring.pass_yd
    points += proj.pass_tds * scoring.pass_td
    points += proj.interceptions * scoring.pass_int
    # Rushing
    points += proj.rush_yards * scoring.rush_yd
    points += proj.rush_tds * scoring.rush_td
    # Receiving
    points += proj.receptions * scoring.rec
    if proj.position == "TE":
        points += proj.receptions * scoring.te_rec_bonus
    points += proj.rec_yards * scoring.rec_yd
    points += proj.rec_tds * scoring.rec_td
    # Misc
    points += proj.fumbles_lost * scoring.fumble_lost
    points += proj.two_pt * scoring.two_pt
    return float(points)


def compute_xfp(
    proj: PlayerProjection,
    scoring: ScoringRules,
    *,
    expected_pass_tds: Optional[float] = None,
    expected_rush_tds: Optional[float] = None,
    expected_rec_tds: Optional[float] = None,
) -> float:
    """Expected fantasy points (xFP) per MATH_MODELS.md.

    ``xFP = sum_p( P(Comp_p) * (AirYds_p * v_rec_yd + E[YAC_p] * v_rec_yd + v_rec)
    + E[RushYds_p] * v_rush_yd + E[TD_p] * v_td + E[2PT_p] * v_2pt )``

    At the season-aggregate level ``sum(AirYds_p + YAC_p)`` equals receiving
    yards and ``sum(P(Comp_p))`` equals receptions, so the receiving half of
    xFP collapses to ``rec_yards * v_rec_yd + receptions * v_rec``.

    Touchdown expectations default to the projected totals; pass alternative
    values to model touchdown regression independently of the raw projection.
    """
    exp_pass_td = proj.pass_tds if expected_pass_tds is None else expected_pass_tds
    exp_rush_td = proj.rush_tds if expected_rush_tds is None else expected_rush_tds
    exp_rec_td = proj.rec_tds if expected_rec_tds is None else expected_rec_tds

    v_rec = scoring.rec + (scoring.te_rec_bonus if proj.position == "TE" else 0.0)

    # Receiving: air yards + YAC earn yardage points; expected completions
    # earn reception points. (sum of air + YAC == receiving yards.)
    rec_xfp = (
        (proj.air_yards + proj.yac) * scoring.rec_yd
        + proj.receptions * v_rec
        + exp_rec_td * scoring.rec_td
    )

    # Rushing expectation.
    rush_xfp = (
        proj.rush_yards * scoring.rush_yd
        + exp_rush_td * scoring.rush_td
    )

    # Passing expectation (QB / occasional rushing positions do not pass).
    pass_xfp = (
        proj.pass_yards * scoring.pass_yd
        + exp_pass_td * scoring.pass_td
        + proj.interceptions * scoring.pass_int
    )

    misc = proj.fumbles_lost * scoring.fumble_lost + proj.two_pt * scoring.two_pt
    return float(rec_xfp + rush_xfp + pass_xfp + misc)


def compute_wopr(proj: PlayerProjection) -> float:
    """Weighted Opportunity Rating.

    ``WOPR = 1.5 * TargetShare + 0.7 * AirYardsShare`` (MATH_MODELS.md §2).
    """
    return float(1.5 * proj.target_share + 0.7 * proj.air_yards_share)


def estimate_epa_per_play(proj: PlayerProjection) -> float:
    """Estimated EPA per play.

    Full play-by-play EPA requires ``nflfastR`` data; until that feed is
    wired in (Phase 2), we use a documented efficiency proxy:

    * QB: regress EPA/play on adjusted yards per dropback, TD rate, and INT rate.
    * Skill: regress EPA/touch on yards per touch vs. a 5-yard neutral baseline.

    The coefficients are order-of-magnitude approximations of public EPA
    values and are intentionally isolated here for easy replacement.
    """
    if proj.position == "QB":
        attempts = proj.pass_attempts + proj.rush_attempts
        if attempts <= 0:
            return 0.0
        dropbacks = max(proj.pass_attempts, 1.0)
        ypa = proj.pass_yards / dropbacks
        td_rate = proj.pass_tds / dropbacks
        int_rate = proj.interceptions / dropbacks
        return float(0.09 * (ypa - 5.0) + 0.9 * td_rate - 1.5 * int_rate)

    touches = proj.rush_attempts + proj.receptions
    if touches <= 0:
        return 0.0
    yards = proj.rush_yards + proj.rec_yards
    return float(0.12 * (yards / touches - 5.0))


def estimate_cpoe(proj: PlayerProjection) -> float:
    """Completion Percentage Over Expected (CPOE).

    ``CPOE = completion_pct - expected_completion_pct`` where the expected
    completion rate is a linear function of average depth of target (aDOT):
    ``expected = 0.75 - 0.035 * aDOT``. For non-QBs CPOE is undefined and
    returns ``0.0``.

    For QBs, ``proj.air_yards`` is interpreted as total passing air yards
    (sum of aDOT across all attempts).
    """
    if proj.position != "QB":
        return 0.0
    attempts = proj.pass_attempts
    if attempts <= 0:
        return 0.0
    adot = proj.air_yards / attempts
    expected_comp_pct = 0.75 - 0.035 * max(adot, 0.0)
    actual_comp_pct = proj.completions / attempts
    return float(actual_comp_pct - expected_comp_pct)


def normalize_derived_metrics(
    players: Sequence[PlayerProjection], scoring: ScoringRules
) -> list[PlayerProjection]:
    """Enrich projections with shares, xFP, WOPR, EPA, CPOE, and fantasy points.

    ``target_share`` and ``air_yards_share`` are computed across the supplied
    pool. (True league/team-level shares require team context, which is added
    once platform data lands in Phase 2; league-wide shares remain a valid
    relative ranking proxy.)
    """
    pool = list(players)
    total_targets = sum(p.targets for p in pool)
    total_air_yards = sum(p.air_yards for p in pool)

    enriched: list[PlayerProjection] = []
    for p in pool:
        p = p.model_copy(deep=True)
        p.target_share = (p.targets / total_targets) if total_targets > 0 else 0.0
        p.air_yards_share = (
            (p.air_yards / total_air_yards) if total_air_yards > 0 else 0.0
        )
        p.wopr = compute_wopr(p)
        p.epa_per_play = estimate_epa_per_play(p)
        p.cpoe = estimate_cpoe(p)
        p.xfp = compute_xfp(p, scoring)
        p.fantasy_points = compute_fantasy_points(p, scoring)
        enriched.append(p)
    return enriched


# ---------------------------------------------------------------------------
# Baseline projection loading (nfl_data_py first, synthetic fallback)
# ---------------------------------------------------------------------------

_DEFAULT_POOL_SIZE: dict[Position, int] = {
    "QB": 30,
    "RB": 54,
    "WR": 66,
    "TE": 36,
}


class ProjectionDataError(RuntimeError):
    """Raised when no external projection source can be loaded."""


def _row_value(df: pd.DataFrame, row: int, *candidates: str, default: float = 0.0) -> float:
    for name in candidates:
        if name in df.columns:
            value = df[name].iloc[row]
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return float(default)


def _row_str(df: pd.DataFrame, row: int, *candidates: str, default: str = "") -> str:
    for name in candidates:
        if name in df.columns:
            value = df[name].iloc[row]
            if pd.notna(value):
                return str(value)
    return default


def load_nfl_players(season: int) -> list[PlayerProjection]:
    """Load season-level player stats from ``nfl_data_py`` into projections.

    ``nfl_data_py.import_seasonal_data`` only carries ``player_id``, so we
    join against ``import_players()`` (keyed by ``gsis_id``) to recover each
    player's display name, position, and team. Column names differ across
    ``nfl_data_py`` releases, so all lookups are defensive; any failure
    raises :class:`ProjectionDataError` for the caller to handle.
    """
    try:
        import nfl_data_py as nfl  # type: ignore
    except Exception as exc:  # pragma: no cover - env dependent
        raise ProjectionDataError(f"nfl_data_py unavailable: {exc}") from exc

    try:
        stats = nfl.import_seasonal_data([season])
        lookup_df = nfl.import_players()
    except Exception as exc:
        raise ProjectionDataError(f"nfl_data_py import failed: {exc}") from exc

    if stats is None or stats.empty:
        raise ProjectionDataError(f"nfl_data_py returned no data for {season}")

    # Build gsis_id -> (name, position, team) lookup.
    lookup: dict[str, tuple[str, str, str]] = {}
    if lookup_df is not None and not lookup_df.empty:
        for row in lookup_df.itertuples(index=False):
            gsis = getattr(row, "gsis_id", None)
            if not gsis:
                continue
            lookup[str(gsis)] = (
                str(getattr(row, "display_name", "") or ""),
                str(getattr(row, "position", "") or "").upper(),
                str(getattr(row, "latest_team", "") or ""),
            )

    players: list[PlayerProjection] = []
    for idx in range(len(stats)):
        raw_id = _row_str(stats, idx, "player_id", "gsis_id")
        name, position, team = lookup.get(raw_id, ("", "", ""))
        if position not in {"QB", "RB", "WR", "TE"}:
            continue

        pass_attempts = _row_value(stats, idx, "attempts", "passing_attempts")
        completions = _row_value(stats, idx, "completions")
        pass_yards = _row_value(stats, idx, "passing_yards")
        pass_tds = _row_value(stats, idx, "passing_tds")
        interceptions = _row_value(stats, idx, "interceptions")
        pass_air_yards = _row_value(stats, idx, "passing_air_yards")
        pass_yac = _row_value(stats, idx, "passing_yards_after_catch")

        rush_attempts = _row_value(stats, idx, "carries", "rushing_attempts")
        rush_yards = _row_value(stats, idx, "rushing_yards")
        rush_tds = _row_value(stats, idx, "rushing_tds")

        targets = _row_value(stats, idx, "targets")
        receptions = _row_value(stats, idx, "receptions")
        rec_yards = _row_value(stats, idx, "receiving_yards")
        rec_tds = _row_value(stats, idx, "receiving_tds")
        rec_air_yards = _row_value(stats, idx, "receiving_air_yards")
        rec_yac = _row_value(stats, idx, "receiving_yards_after_catch")

        if position == "QB":
            air_yards = pass_air_yards
            yac = pass_yac
        else:
            air_yards = rec_air_yards
            yac = rec_yac

        fumbles_lost = _row_value(
            stats, idx, "sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"
        )
        two_pt = _row_value(
            stats, idx, "passing_2pt_conversions", "rushing_2pt_conversions",
            "receiving_2pt_conversions",
        )

        players.append(
            PlayerProjection(
                player_id=raw_id or name,
                name=name or raw_id,
                position=position,  # type: ignore[arg-type]
                team=team,
                pass_attempts=pass_attempts,
                completions=completions,
                pass_yards=pass_yards,
                pass_tds=pass_tds,
                interceptions=interceptions,
                rush_attempts=rush_attempts,
                rush_yards=rush_yards,
                rush_tds=rush_tds,
                targets=targets,
                receptions=receptions,
                rec_yards=rec_yards,
                rec_tds=rec_tds,
                air_yards=air_yards,
                yac=yac,
                target_share=_row_value(stats, idx, "target_share"),
                air_yards_share=_row_value(stats, idx, "air_yards_share"),
                fumbles_lost=fumbles_lost,
                two_pt=two_pt,
            )
        )
    return players


def generate_synthetic_pool(
    *,
    seed: int = 42,
    pool_size: Optional[dict[Position, int]] = None,
) -> list[PlayerProjection]:
    """Generate a deterministic, realistic-looking projection pool.

    This fallback keeps the engine fully functional offline and in CI. The
    RNG is seeded so top recommendations are reproducible.
    """
    rng = random.Random(seed)
    sizes = {**_DEFAULT_POOL_SIZE, **(pool_size or {})}

    def r(lo: float, hi: float) -> float:
        return round(rng.uniform(lo, hi), 2)

    players: list[PlayerProjection] = []
    for position in ("QB", "RB", "WR", "TE"):
        for rank in range(1, sizes[position] + 1):
            # Talent factor decays with rank; rank 1 is the best player.
            talent = max(0.35, 1.0 - 0.045 * (rank - 1))

            if position == "QB":
                att = round(560 * talent * r(0.85, 1.1))
                comp = round(att * r(0.62, 0.70))
                pyd = round(att * r(7.1, 8.2))
                ptd = round(pyd / r(115, 145))
                ints = round(att * r(0.018, 0.034))
                air = round(att * r(7.0, 8.8))
                yac = round(max(pyd - air, 0.0))
                proj = PlayerProjection(
                    player_id=f"QB{rank:02d}",
                    name=f"Quarterback {rank}",
                    position="QB",
                    team=f"TM{rank % 32:02d}",
                    pass_attempts=att,
                    completions=comp,
                    pass_yards=pyd,
                    pass_tds=ptd,
                    interceptions=ints,
                    rush_attempts=round(r(25, 85) * talent),
                    rush_yards=round(r(120, 520) * talent),
                    rush_tds=round(r(0.5, 6.0) * talent),
                    air_yards=air,
                    yac=yac,
                    fumbles_lost=round(r(1, 5) * talent, 1),
                    two_pt=round(r(0, 2) * talent, 1),
                )
            elif position == "RB":
                carries = round(270 * talent * r(0.8, 1.15))
                ryd = round(carries * r(4.0, 5.2))
                targets = round(70 * talent * r(0.6, 1.3))
                recs = round(targets * r(0.72, 0.84))
                ry = round(recs * r(5.5, 8.5))
                air = round(ry * r(0.10, 0.30))
                yac = round(ry - air, 2)
                proj = PlayerProjection(
                    player_id=f"RB{rank:02d}",
                    name=f"Running Back {rank}",
                    position="RB",
                    team=f"TM{rank % 32:02d}",
                    rush_attempts=carries,
                    rush_yards=ryd,
                    rush_tds=round(r(3, 14) * talent),
                    targets=targets,
                    receptions=recs,
                    rec_yards=ry,
                    rec_tds=round(r(0, 5) * talent, 1),
                    air_yards=air,
                    yac=yac,
                    fumbles_lost=round(r(1, 4) * talent, 1),
                    two_pt=round(r(0, 1) * talent, 1),
                )
            elif position == "WR":
                targets = round(150 * talent * r(0.75, 1.2))
                recs = round(targets * r(0.60, 0.72))
                ry = round(recs * r(11.0, 15.0))
                air = round(ry * r(0.55, 0.75))
                yac = round(ry - air, 2)
                proj = PlayerProjection(
                    player_id=f"WR{rank:02d}",
                    name=f"Wide Receiver {rank}",
                    position="WR",
                    team=f"TM{rank % 32:02d}",
                    rush_attempts=round(r(0, 12) * talent),
                    rush_yards=round(r(0, 70) * talent),
                    rush_tds=round(r(0, 1) * talent, 1),
                    targets=targets,
                    receptions=recs,
                    rec_yards=ry,
                    rec_tds=round(r(3, 12) * talent),
                    air_yards=air,
                    yac=yac,
                    fumbles_lost=round(r(0, 2) * talent, 1),
                    two_pt=round(r(0, 1) * talent, 1),
                )
            else:  # TE
                targets = round(105 * talent * r(0.7, 1.25))
                recs = round(targets * r(0.66, 0.78))
                ry = round(recs * r(9.0, 12.5))
                air = round(ry * r(0.45, 0.65))
                yac = round(ry - air, 2)
                proj = PlayerProjection(
                    player_id=f"TE{rank:02d}",
                    name=f"Tight End {rank}",
                    position="TE",
                    team=f"TM{rank % 32:02d}",
                    rush_attempts=round(r(0, 5) * talent),
                    rush_yards=round(r(0, 25) * talent),
                    rush_tds=round(r(0, 0.5) * talent, 1),
                    targets=targets,
                    receptions=recs,
                    rec_yards=ry,
                    rec_tds=round(r(2, 10) * talent),
                    air_yards=air,
                    yac=yac,
                    fumbles_lost=round(r(0, 2) * talent, 1),
                    two_pt=round(r(0, 1) * talent, 1),
                )

            # Historical ADP volatility and a deterministic bye week (5-14).
            proj.adp_std = round(r(2.5, 6.0), 2)
            proj.bye_week = 5 + (rank % 10)
            players.append(proj)

    # Assign ADP from a reference (full-PPR) value ranking so ADP ordering is
    # stable regardless of the active league config.
    reference = ScoringRules(rec=1.0)
    ranked = sorted(
        players,
        key=lambda p: (compute_fantasy_points(p, reference), p.player_id),
        reverse=True,
    )
    for pick, p in enumerate(ranked, start=1):
        p.adp = float(pick)
        p.adp_std = getattr(p, "adp_std", 4.5)
    return players


def assign_value_adp(
    players: Sequence[PlayerProjection],
) -> list[PlayerProjection]:
    """Assign a value-based ADP proxy to any player missing one.

    A true ADP source (FantasyPros, platform ADP) is wired in Phase 2. Until
    then, ADP is approximated by ranking a full-PPR reference score so the
    Make-It-Back probability remains well-defined. Players that already carry
    an ADP are left untouched.
    """
    reference = ScoringRules(rec=1.0)
    ranked = sorted(
        players,
        key=lambda p: (compute_fantasy_points(p, reference), p.player_id),
        reverse=True,
    )
    for pick, p in enumerate(ranked, start=1):
        if p.adp is None:
            p.adp = float(pick)
    return list(players)


def build_projection_pool(
    config: LeagueConfig,
    *,
    season: int = 2024,
    allow_network: bool = True,
    seed: int = 42,
    pool_size: Optional[dict[Position, int]] = None,
) -> list[PlayerProjection]:
    """Build an enriched, scoring-aware projection pool.

    Attempts ``nfl_data_py`` first; if the import, network download, or data
    mapping fails, falls back to the deterministic synthetic pool. ADP is
    assigned from a value proxy when the source does not provide it.
    """
    raw: list[PlayerProjection] = []
    if allow_network:
        try:
            raw = load_nfl_players(season)
            if not raw:
                raise ProjectionDataError("no qualifying players returned")
            logger.info("Loaded %d players from nfl_data_py (season %d)", len(raw), season)
        except ProjectionDataError as exc:
            logger.warning("Falling back to synthetic pool: %s", exc)

    if not raw:
        raw = generate_synthetic_pool(seed=seed, pool_size=pool_size)
        logger.info("Using synthetic pool with %d players", len(raw))

    raw = assign_value_adp(raw)
    return normalize_derived_metrics(raw, config.scoring)


def filter_available(
    players: Sequence[PlayerProjection], drafted_ids: set[str] | frozenset[str]
) -> list[PlayerProjection]:
    """Return projections whose ``player_id`` has not been drafted."""
    return [p for p in players if p.player_id not in drafted_ids]


if __name__ == "__main__":  # pragma: no cover - interactive smoke test
    logging.basicConfig(level=logging.INFO)
    cfg = LeagueConfig.full_ppr()
    pool = build_projection_pool(cfg, season=2023)
    by_pos: dict[str, int] = {}
    for p in pool:
        by_pos[p.position] = by_pos.get(p.position, 0) + 1
    print(f"Pool: {len(pool)} players {by_pos}")
    print("Top 5 by fantasy points:")
    for p in sorted(pool, key=lambda x: x.fantasy_points, reverse=True)[:5]:
        print(
            f"  {p.name:20s} {p.position:2s} FP={p.fantasy_points:6.1f} "
            f"xFP={p.xfp:6.1f} WOPR={p.wopr:5.3f} EPA={p.epa_per_play: .3f} "
            f"CPOE={p.cpoe: .3f} ADP={p.adp}"
        )