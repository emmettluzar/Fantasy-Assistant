"""Analytics engine for the Fantasy Draft Assistant.

Public API surface for Phase 1: baseline projections, dynamic VORP, and the
master decision utility (Make-It-Back probability plus roster-need / bye
logic).
"""

from .dvorp import (
    ReplacementBaseline,
    DvorpResult,
    compute_all_dvorp,
    compute_baselines,
    compute_dvorp,
    compute_replacement_baseline,
    count_drafted_by_pos,
    rank_by_dvorp,
)
from .models import (
    DEFAULT_ADP_STD,
    FLEX_ALLOCATION,
    DraftPick,
    LeagueConfig,
    PlayerProjection,
    Position,
    RosterSettings,
    ScoringRules,
)
from .probability import (
    DecisionContext,
    DecisionWeights,
    UtilityComponents,
    bye_overlap_penalty,
    compute_player_dvorp_map,
    decision_utility,
    make_it_back_matrix,
    make_it_back_probability,
    rank_decisions,
    roster_need_factor,
    score_decision,
)
from .projections import (
    ProjectionDataError,
    build_projection_pool,
    compute_fantasy_points,
    compute_wopr,
    compute_xfp,
    estimate_cpoe,
    estimate_epa_per_play,
    filter_available,
    generate_synthetic_pool,
    load_nfl_players,
    normalize_derived_metrics,
)

__all__ = [
    "DEFAULT_ADP_STD",
    "FLEX_ALLOCATION",
    "DecisionContext",
    "DecisionWeights",
    "DraftPick",
    "DvorpResult",
    "LeagueConfig",
    "PlayerProjection",
    "Position",
    "ProjectionDataError",
    "ReplacementBaseline",
    "RosterSettings",
    "ScoringRules",
    "UtilityComponents",
    "build_projection_pool",
    "bye_overlap_penalty",
    "compute_all_dvorp",
    "compute_baselines",
    "compute_dvorp",
    "compute_fantasy_points",
    "compute_player_dvorp_map",
    "compute_replacement_baseline",
    "compute_wopr",
    "compute_xfp",
    "count_drafted_by_pos",
    "decision_utility",
    "estimate_cpoe",
    "estimate_epa_per_play",
    "filter_available",
    "generate_synthetic_pool",
    "load_nfl_players",
    "make_it_back_matrix",
    "make_it_back_probability",
    "normalize_derived_metrics",
    "rank_by_dvorp",
    "rank_decisions",
    "roster_need_factor",
    "score_decision",
]