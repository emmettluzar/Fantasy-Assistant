"""WebSocket message schema for the Fantasy Draft Assistant IPC bridge.

Canonical contract lives in ``IPC_PROTOCOL.md``; this module is kept in
lockstep with:

* ``src/types/protocol.ts``   (TypeScript)
* ``src-tauri/src/protocol.rs`` (Rust)

Wire-format notes
-----------------
The canonical serialization comes from the pydantic models in
:mod:`engine.models`, so scoring fields use snake_case keys (``pass_yd``,
``rec_td``, ...) and roster slots use UPPERCASE keys (``QB``, ``FLEX``, ...).
Every frame on the wire has the envelope::

    {"type": "<TYPE>", "payload": { ... }, "request_id": "<id>"}
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from engine.models import LeagueConfig, Position

# Number of recommendations returned by GET_RECOMMENDATIONS unless overridden.
DEFAULT_LIMIT: int = 8
MAX_LIMIT: int = 50


class SyncLeagueConfigPayload(LeagueConfig):
    """Payload for ``SYNC_LEAGUE_CONFIG``.

    Extends :class:`engine.models.LeagueConfig` with transport-level fields
    that are not part of the scoring model itself:

    * ``user_team_index``: 0-based index of the user's drafting team.
    * ``allow_network``: whether the server may download live projections from
      ``nfl_data_py`` (otherwise it uses the offline synthetic pool).
    """

    user_team_index: int = Field(default=0, ge=0)
    allow_network: bool = Field(default=False)

    def to_league_config(self) -> LeagueConfig:
        """Strip transport fields, returning the pure :class:`LeagueConfig`."""
        return LeagueConfig(
            name=self.name,
            scoring=self.scoring,
            roster_slots=self.roster_slots,
            teams_count=self.teams_count,
            is_dynasty=self.is_dynasty,
        )


class PlatformRosterPlayer(BaseModel):
    """A rostered player returned by a platform adapter during league sync.

    ``position`` is intentionally a free-form string rather than the engine's
    ``Position`` literal: adapters may emit non-skill codes (``BENCH``,
    ``SUPERFLEX``, ...) that the engine does not model.
    """

    player_id: str
    name: Optional[str] = None
    position: Optional[str] = None


class PlatformRoster(BaseModel):
    """A single team's roster keyed by a stable 0-based ``team_index``."""

    team_index: int = Field(ge=0)
    team_name: str = ""
    players: list[PlatformRosterPlayer] = Field(default_factory=list)


class PlatformLeagueTeam(BaseModel):
    """A single team surfaced in a ``PLATFORM_LEAGUE_SYNCED`` response.

    ``team_id`` is the platform's stable roster identifier (falling back to the
    stringified 0-based index when a platform does not expose one). ``team_index``
    is the 0-based slot the engine uses; the client maps the user's selected team
    back to this index when saving the user team.
    """

    team_id: str
    team_name: str = ""
    team_index: int = Field(ge=0)
    is_user: bool = False


class PlatformLeagueSyncedPayload(BaseModel):
    """Response payload for ``PLATFORM_LEAGUE_SYNCED``.

    Carries the applied :class:`LeagueConfig`, the normalized team list, and the
    raw roster records so the client can populate the board + dashboard without
    a follow-up request.
    """

    platform: str = Field(pattern="^(sleeper|espn|yahoo)$")
    league_id: Optional[str] = None
    config: LeagueConfig
    teams: list[PlatformLeagueTeam] = Field(default_factory=list)
    rosters: list[PlatformRoster] = Field(default_factory=list)
    # 0-based slot the engine treats as the user's drafting team. For ESPN/Yahoo
    # this is decided after the team list is returned; the client re-applies the
    # config once the user picks a team.
    user_team_index: int = Field(default=0, ge=0)


class SyncPlatformLeaguePayload(BaseModel):
    """Payload for ``SYNC_PLATFORM_LEAGUE``.

    ``platform`` selects the adapter; the remaining fields are adapter-specific
    credentials/locators. ``user_team_index`` is only honored for platforms that
    resolve a user-owned team during sync (Sleeper); otherwise it defaults to 0.
    """

    platform: str = Field(pattern="^(sleeper|espn|yahoo)$")
    league_id: Optional[str] = None
    # Season is shared by ESPN/Sleeper league lookups; ``year`` is a legacy
    # alias kept for backward compatibility with older desktop clients.
    season: Optional[int] = None
    year: Optional[int] = None
    # Sleeper
    draft_id: Optional[str] = None
    username: Optional[str] = None
    user_team_index: int = Field(default=0, ge=0)
    # ESPN
    espn_s2: Optional[str] = None
    swid: Optional[str] = None
    # Yahoo
    oauth_key: Optional[str] = None
    allow_network: bool = Field(default=False)


class GetRecommendationsPayload(BaseModel):
    """Payload for ``GET_RECOMMENDATIONS``.

    All fields are optional; the server falls back to the values established by
    ``SYNC_LEAGUE_CONFIG`` (``user_team_index``) or derived from the live draft
    board (``r_next``).
    """

    user_team_index: Optional[int] = Field(default=None, ge=0)
    r_next: Optional[float] = Field(default=None, ge=0)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)


class DraftPickMadePayload(BaseModel):
    """Payload for ``DRAFT_PICK_MADE``.

    ``position`` and ``fantasy_points`` are optional on the wire because the
    server derives them from its projection pool; they let platform adapters
    forward a minimal pick event and still remain unambiguous.
    """

    pick_number: int = Field(ge=1)
    round: int = Field(ge=1)
    team_index: int = Field(ge=0)
    player_id: str
    position: Optional[Position] = Field(default=None)
    fantasy_points: Optional[float] = Field(default=None, ge=0)
    timestamp: Optional[float] = Field(default=None)


class ResetDraftPayload(BaseModel):
    """Payload for ``RESET_DRAFT``."""

    keep_config: bool = Field(
        default=True, description="Keep the current LeagueConfig when resetting"
    )


class RosterPlayerPayload(BaseModel):
    """A rostered player used by the in-season optimizer/trade analyzer.

    ``fantasy_points`` is the projected weekly (or rest-of-season) total; the
    server derives it from the pool when omitted.
    """

    player_id: str
    name: str = ""
    position: Position
    fantasy_points: Optional[float] = Field(default=None, ge=0)
    team: str = ""
    injury_tag: Optional[str] = Field(default=None)
    weather: Optional[str] = Field(default=None)
    ceiling: Optional[float] = Field(default=None, ge=0)
    floor: Optional[float] = Field(default=None, ge=0)


class OptimizeLineupPayload(BaseModel):
    """Payload for ``OPTIMIZE_LINEUP``."""

    roster: list[RosterPlayerPayload]


class EvaluateTradePayload(BaseModel):
    """Payload for ``EVALUATE_TRADE``."""

    user_roster: list[RosterPlayerPayload]
    opponent_roster: list[RosterPlayerPayload]
    user_gives: list[str] = Field(default_factory=list)
    user_receives: list[str] = Field(default_factory=list)
    current_week: int = Field(default=1, ge=1, le=18)
    opponent_expected_points: Optional[float] = Field(default=None, ge=0)


class CalculateFaabBidsPayload(BaseModel):
    """Payload for ``CALCULATE_FAAB_BIDS``.

    ``free_agents`` and ``all_players`` carry projected totals. When empty the
    server fills them from its projection pool.
    """

    free_agents: list[RosterPlayerPayload] = Field(default_factory=list)
    all_players: list[RosterPlayerPayload] = Field(default_factory=list)
    current_week: int = Field(default=1, ge=1, le=18)
    user_budget: float = Field(default=100.0, ge=0)
    roster_need: dict[str, int] = Field(default_factory=dict)
    rival_need_by_pos: dict[str, int] = Field(default_factory=dict)
    rival_faab: list[float] = Field(default_factory=list)


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "SyncLeagueConfigPayload",
    "GetRecommendationsPayload",
    "DraftPickMadePayload",
    "ResetDraftPayload",
    "RosterPlayerPayload",
    "OptimizeLineupPayload",
    "EvaluateTradePayload",
    "CalculateFaabBidsPayload",
    "SyncPlatformLeaguePayload",
    "PlatformRoster",
    "PlatformRosterPlayer",
    "PlatformLeagueTeam",
    "PlatformLeagueSyncedPayload",
]
