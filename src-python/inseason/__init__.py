"""In-season automation analytics engine (Phase 5).

Exposes three subsystems used by the local WebSocket server:

* :mod:`inseason.waivers`   -- Rest-Of-Season DVORP + optimal FAAB bidding
* :mod:`inseason.trades`    -- Trade Analyzer (delta utility + win probability)
* :mod:`inseason.optimizer` -- MILP lineup optimizer with weather/injury penalties

All modules consume the shared :class:`~engine.models.LeagueConfig` and
:class:`~engine.models.PlayerProjection` models so custom league scoring flows
through every in-season calculation without duplicated math.
"""

from .optimizer import (
    LineupOptimization,
    LineupSlot,
    RosterPlayer,
    adjusted_projection,
    optimize_lineup,
)
from .trades import (
    PLAYOFF_WEEKS,
    TradeEvaluation,
    evaluate_trade,
    roster_utility,
    season_adjusted_points,
    win_probability,
)
from .waivers import (
    DEFAULT_BUDGET,
    FaabBid,
    calculate_faab_bids,
    compute_ros_dvorp,
    optimal_faab_bid,
    ros_projection,
)

__all__ = [
    "DEFAULT_BUDGET",
    "FaabBid",
    "LineupOptimization",
    "LineupSlot",
    "PLAYOFF_WEEKS",
    "RosterPlayer",
    "TradeEvaluation",
    "adjusted_projection",
    "calculate_faab_bids",
    "compute_ros_dvorp",
    "evaluate_trade",
    "optimal_faab_bid",
    "optimize_lineup",
    "ros_projection",
    "roster_utility",
    "season_adjusted_points",
    "win_probability",
]