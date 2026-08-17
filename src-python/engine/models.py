"""Core Pydantic models and default league presets for the analytics engine.

This module is the single source of truth for the league configuration
schema, scoring multipliers, projected player statistics, and draft events.
Every downstream calculation (xFP, WOPR, DVORP, P_MB, U_i(t)) consumes these
models so that a custom league's scoring rules flow through the entire
pipeline without manual intervention.
"""

from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Fixed positional vocabulary used throughout the engine.
Position = Literal["QB", "RB", "WR", "TE", "K", "DST"]

SKILL_POSITIONS: tuple[Position, ...] = ("QB", "RB", "WR", "TE")
FLEX_ELIGIBLE: tuple[Position, ...] = ("RB", "WR", "TE")

# How FLEX slots are distributed across eligible positions when computing
# replacement baselines. Wide receivers dominate modern flex usage, followed
# by running backs and a small tight-end allocation.
FLEX_ALLOCATION: Dict[str, float] = {"RB": 0.40, "WR": 0.50, "TE": 0.10}

# Historical standard deviation used when a player's ADP volatility is unknown.
DEFAULT_ADP_STD: float = 4.5


class ScoringRules(BaseModel):
    """Multipliers applied to each raw statistic to derive fantasy points.

    Defaults match the MATH_MODELS.md schema (Standard scoring):
    * passing yards: 1 pt / 25 yds  -> 0.04
    * rushing yards: 1 pt / 10 yds  -> 0.1
    * receiving yards: 1 pt / 10 yds -> 0.1
    """

    pass_yd: float = Field(default=0.04, description="Points per passing yard")
    pass_td: float = Field(default=4.0, description="Points per passing touchdown")
    pass_int: float = Field(default=-2.0, description="Points per interception")
    rush_yd: float = Field(default=0.1, description="Points per rushing yard")
    rush_td: float = Field(default=6.0, description="Points per rushing touchdown")
    rec: float = Field(default=0.0, description="Points per reception (PPR)")
    rec_yd: float = Field(default=0.1, description="Points per receiving yard")
    rec_td: float = Field(default=6.0, description="Points per receiving touchdown")
    te_rec_bonus: float = Field(default=0.0, description="Extra points per TE reception (TE premium)")
    fumble_lost: float = Field(default=-2.0, description="Points per fumble lost")
    two_pt: float = Field(default=2.0, description="Points per two-point conversion")

    model_config = ConfigDict(frozen=False, extra="forbid")


class RosterSettings(BaseModel):
    """Number of starting slots per position for each team.

    Defaults match the MATH_MODELS.md schema:
    QB=1, RB=2, WR=2, TE=1, FLEX=1, SUPERFLEX=0, BENCH=6.
    """

    QB: int = Field(default=1, ge=0)
    RB: int = Field(default=2, ge=0)
    WR: int = Field(default=2, ge=0)
    TE: int = Field(default=1, ge=0)
    FLEX: int = Field(default=1, ge=0)
    SUPERFLEX: int = Field(default=0, ge=0)
    BENCH: int = Field(default=6, ge=0)
    K: int = Field(default=0, ge=0)
    DST: int = Field(default=0, ge=0)

    model_config = ConfigDict(frozen=False, extra="forbid")

    def positional_slots(self, position: Position, *, include_flex: bool = True) -> float:
        """Effective number of starting slots consumed by ``position``.

        Superflex counts toward QB, and FLEX slots are distributed across
        RB/WR/TE using :data:`FLEX_ALLOCATION`.
        """
        base = float(getattr(self, position, 0))
        if position == "QB":
            base += float(self.SUPERFLEX)
        if include_flex and position in FLEX_ELIGIBLE:
            base += float(self.FLEX) * FLEX_ALLOCATION.get(position, 0.0)
        return base

    def total_starters(self) -> int:
        """Total weekly starting slots per team (excluding bench)."""
        return (
            self.QB
            + self.RB
            + self.WR
            + self.TE
            + self.FLEX
            + self.SUPERFLEX
            + self.K
            + self.DST
        )

    def total_roster(self) -> int:
        """Total roster size per team (starters + bench)."""
        return self.total_starters() + self.BENCH


class LeagueConfig(BaseModel):
    """A fully specified league whose rules drive all calculations."""

    name: str = "Custom"
    scoring: ScoringRules = Field(default_factory=ScoringRules)
    roster_slots: RosterSettings = Field(default_factory=RosterSettings)
    teams_count: int = Field(default=12, ge=2, le=32)

    model_config = ConfigDict(frozen=False, extra="forbid")

    def replacement_slots(self, position: Position, *, include_flex: bool = True) -> float:
        """League-wide replacement slot count for a position.

        ``teams_count * roster_slots[p]`` per MATH_MODELS.md, expanded for
        superflex and flex allocations.
        """
        return self.teams_count * self.roster_slots.positional_slots(
            position, include_flex=include_flex
        )

    def total_rounds(self) -> int:
        """Number of draft rounds (roster size)."""
        return self.roster_slots.total_roster()

    # ------------------------------------------------------------------
    # Default presets
    # ------------------------------------------------------------------
    @classmethod
    def standard(cls) -> "LeagueConfig":
        """Standard scoring (no PPR, 4-pt passing TDs)."""
        return cls(name="Standard", scoring=ScoringRules(rec=0.0, te_rec_bonus=0.0))

    @classmethod
    def half_ppr(cls) -> "LeagueConfig":
        """Half-PPR scoring."""
        return cls(name="Half-PPR", scoring=ScoringRules(rec=0.5))

    @classmethod
    def full_ppr(cls) -> "LeagueConfig":
        """Full-PPR scoring."""
        return cls(name="Full-PPR", scoring=ScoringRules(rec=1.0))

    @classmethod
    def superflex(cls) -> "LeagueConfig":
        """Superflex (adds a QB-eligible flex slot)."""
        return cls(
            name="Superflex",
            scoring=ScoringRules(rec=1.0),
            roster_slots=RosterSettings(SUPERFLEX=1),
        )

    @classmethod
    def te_premium(cls) -> "LeagueConfig":
        """TE-Premium (full PPR with an extra point per TE reception)."""
        return cls(
            name="TE-Premium",
            scoring=ScoringRules(rec=1.0, te_rec_bonus=1.0),
        )

    @classmethod
    def presets(cls) -> Dict[str, "LeagueConfig"]:
        """All built-in presets keyed by display name."""
        return {
            "Standard": cls.standard(),
            "Half-PPR": cls.half_ppr(),
            "Full-PPR": cls.full_ppr(),
            "Superflex": cls.superflex(),
            "TE-Premium": cls.te_premium(),
        }


class PlayerProjection(BaseModel):
    """Season-long projected statistics and derived metrics for one player."""

    player_id: str
    name: str
    position: Position
    team: str = ""

    adp: Optional[float] = Field(default=None, description="Average draft position (overall pick)")
    adp_std: float = Field(default=DEFAULT_ADP_STD, description="Historical ADP standard deviation")
    bye_week: int = Field(default=0, description="NFL bye week (0 = unknown)")

    # Passing
    pass_attempts: float = Field(default=0.0)
    completions: float = Field(default=0.0)
    pass_yards: float = Field(default=0.0)
    pass_tds: float = Field(default=0.0)
    interceptions: float = Field(default=0.0)

    # Rushing
    rush_attempts: float = Field(default=0.0)
    rush_yards: float = Field(default=0.0)
    rush_tds: float = Field(default=0.0)

    # Receiving / usage
    targets: float = Field(default=0.0)
    receptions: float = Field(default=0.0)
    rec_yards: float = Field(default=0.0)
    rec_tds: float = Field(default=0.0)
    air_yards: float = Field(default=0.0)
    yac: float = Field(default=0.0)

    # Misc
    fumbles_lost: float = Field(default=0.0)
    two_pt: float = Field(default=0.0)

    # Usage shares
    target_share: float = Field(default=0.0)
    air_yards_share: float = Field(default=0.0)

    # Derived metrics
    xfp: float = Field(default=0.0, description="Expected fantasy points")
    wopr: float = Field(default=0.0, description="Weighted Opportunity Rating")
    epa_per_play: float = Field(default=0.0, description="EPA per play")
    cpoe: float = Field(default=0.0, description="Completion Percentage Over Expected")
    fantasy_points: float = Field(default=0.0, description="Projected fantasy points under active scoring")

    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class DraftPick(BaseModel):
    """A single normalized draft event."""

    pick_number: int = Field(ge=1, description="Overall pick number (1-based)")
    round: int = Field(ge=1)
    team_index: int = Field(ge=0, description="0-based drafting team index")
    player_id: str
    position: Position
    fantasy_points: float = 0.0
    timestamp: Optional[float] = None

    model_config = ConfigDict(extra="ignore")