"""Sleeper platform adapter.

Sleeper exposes a pure JSON REST API plus a draft-room WebSocket. This adapter
ingests:

* league scoring settings (mapped to the engine's :class:`LeagueConfig`),
* rosters (used to resolve ``picked_by`` / ``roster_id`` to a stable
  0-based ``team_index``),
* live draft picks via REST polling and/or the draft WebSocket stream.

All endpoints are read-only and require no authentication for public drafts.

Endpoint reference:
    * ``GET  /draft/{draft_id}``
    * ``GET  /draft/{draft_id}/picks``
    * ``GET  /league/{league_id}``
    * ``GET  /league/{league_id}/rosters``
    * ``GET  /players/nfl``
    * ``WS   wss://draft.sleeper.app/websocket``
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional

from .normalizer import PlayerNormalizer

SLEEPER_API = "https://api.sleeper.app/v1"
SLEEPER_DRAFT_WS = "wss://draft.sleeper.app/websocket"

# Map Sleeper league scoring keys to engine ``ScoringRules`` snake_case keys.
_SCORING_MAP: dict[str, str] = {
    "pass_yd": "pass_yd",
    "pass_td": "pass_td",
    "pass_int": "pass_int",
    "int": "pass_int",
    "int_pts": "pass_int",
    "rush_yd": "rush_yd",
    "rush_td": "rush_td",
    "rec": "rec",
    "rec_yd": "rec_yd",
    "rec_td": "rec_td",
    "te_rec_bonus": "te_rec_bonus",
    "bonus_rec_te": "te_rec_bonus",
    "fum_lost": "fumble_lost",
    "fumble_lost": "fumble_lost",
    "two_pt": "two_pt",
    "2pt": "two_pt",
}

# Sleeper roster position codes -> engine UPPERCASE slot keys.
_SLOT_MAP: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "FLEX": "FLEX",
    "WRRB_FLEX": "FLEX",
    "REC_FLEX": "FLEX",
    "SUPER_FLEX": "SUPERFLEX",
    "K": "K",
    "DEF": "DST",
    "DST": "DST",
    "BN": "BENCH",
}


class SleeperAdapter:
    """REST + WebSocket ingestion for a single Sleeper draft."""

    def __init__(
        self,
        draft_id: Optional[str] = None,
        *,
        league_id: Optional[str] = None,
        api_url: str = SLEEPER_API,
    ) -> None:
        self.draft_id = draft_id
        self.league_id = str(league_id) if league_id else None
        self.api_url = api_url.rstrip("/")
        self.normalizer = PlayerNormalizer()
        self._draft: Optional[dict[str, Any]] = None
        self._league: Optional[dict[str, Any]] = None
        self._rosters: Optional[list[dict[str, Any]]] = None
        self._slot_to_roster: dict[int, str] = {}

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    def _get(self, path: str) -> dict[str, Any] | list[Any]:
        import requests  # local import: adapter is optional at runtime

        response = requests.get(f"{self.api_url}{path}", timeout=15)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------
    def fetch_draft(self) -> dict[str, Any]:
        """Fetch and cache the draft object."""
        if self._draft is None:
            self._draft = dict(self._get(f"/draft/{self.draft_id}") or {})
            self._ingest_slot_mapping()
        return self._draft

    def _resolve_league_id(self) -> str:
        """Return the league id, deriving it from the draft when not provided.

        League-only sync (``SYNC_PLATFORM_LEAGUE``) supplies ``league_id``
        directly; draft streaming derives it from the draft object.
        """
        if self.league_id:
            return self.league_id
        draft = self.fetch_draft()
        league_id = draft.get("league_id")
        if not league_id:
            raise ValueError("Sleeper draft is missing a league_id")
        self.league_id = str(league_id)
        return self.league_id

    def fetch_league(self) -> dict[str, Any]:
        """Fetch and cache the league settings object."""
        if self._league is None:
            self._league = dict(self._get(f"/league/{self._resolve_league_id()}") or {})
        return self._league

    def fetch_rosters(self) -> list[dict[str, Any]]:
        """Fetch and cache league rosters for team-index resolution."""
        if self._rosters is None:
            data = self._get(f"/league/{self._resolve_league_id()}/rosters")
            self._rosters = [dict(r) for r in (data or []) if isinstance(r, dict)]
        return self._rosters

    def fetch_picks(self) -> list[dict[str, Any]]:
        """Return the raw picks for this draft."""
        data = self._get(f"/draft/{self.draft_id}/picks")
        return [dict(p) for p in (data or []) if isinstance(p, dict)]

    def _ingest_slot_mapping(self) -> None:
        """Map Sleeper ``slot_to_roster_id`` for team-index resolution."""
        mapping = self._draft.get("slot_to_roster_id") if self._draft else None
        if isinstance(mapping, dict):
            self._slot_to_roster = {
                int(slot): str(roster_id) for slot, roster_id in mapping.items()
            }

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    def _resolve_team_index(self, pick: dict[str, Any]) -> int:
        """Resolve a stable 0-based team index from a Sleeper pick.

        Preference order: ``draft_slot`` (1-based) -> ``roster_id`` position
        in the league roster list -> ``picked_by`` position.
        """
        draft_slot = pick.get("draft_slot")
        if draft_slot is not None:
            try:
                return int(draft_slot) - 1
            except (TypeError, ValueError):
                pass

        roster_id = str(pick.get("roster_id") or pick.get("picked_by") or "")
        rosters = self._rosters or []
        for index, roster in enumerate(rosters):
            if str(roster.get("roster_id") or roster.get("owner_id")) == roster_id:
                return index
        return 0

    def normalize_pick(self, pick: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Normalize one raw Sleeper pick into an engine-ready dict."""
        metadata = pick.get("metadata") or {}
        player_name = " ".join(
            part
            for part in (
                metadata.get("player_first_name"),
                metadata.get("player_last_name"),
            )
            if part
        ).strip()

        player_id = str(pick.get("player_id") or player_name or "")
        position = metadata.get("position") or None
        team = metadata.get("team") or None

        # Resolve first so a pre-seeded cross-platform mapping wins; only
        # register a fresh canonical record when the identity is unknown.
        if player_id:
            resolved = self.normalizer.resolve(
                platform="sleeper",
                platform_id=player_id,
                name=player_name,
            )
            if resolved is None:
                self.normalizer.register(
                    player_id=player_id,
                    name=player_name or player_id,
                    position=position,
                    team=team,
                    platform="sleeper",
                    platform_id=player_id,
                )

        return self.normalizer.normalize_pick(
            {
                "player_id": player_id,
                "name": player_name,
                "position": position,
                "team_index": self._resolve_team_index(pick),
                "round": pick.get("round"),
                "pick_number": pick.get("pick_no") or pick.get("pick_number"),
                "timestamp": pick.get("picked_at") or pick.get("timestamp"),
            },
            platform="sleeper",
        )

    def normalize_picks(self) -> list[dict[str, Any]]:
        """Fetch and normalize all current picks."""
        raw = self.fetch_picks()
        self.fetch_rosters()  # ensure team-index resolution has roster order
        return list(filter(None, (self.normalize_pick(p) for p in raw)))

    # ------------------------------------------------------------------
    # League configuration mapping
    # ------------------------------------------------------------------
    def to_league_config(self) -> dict[str, Any]:
        """Map Sleeper league settings to the engine ``LeagueConfig`` schema."""
        league = self.fetch_league()
        self.fetch_rosters()  # ensure teams_count can be derived from rosters
        settings = dict(league.get("settings") or league.get("scoring_settings") or {})

        scoring: dict[str, float] = {
            "pass_yd": 0.04,
            "pass_td": 4.0,
            "pass_int": -2.0,
            "rush_yd": 0.1,
            "rush_td": 6.0,
            "rec": 0.0,
            "rec_yd": 0.1,
            "rec_td": 6.0,
            "te_rec_bonus": 0.0,
            "fumble_lost": -2.0,
            "two_pt": 2.0,
        }
        for sleeper_key, engine_key in _SCORING_MAP.items():
            if sleeper_key in settings:
                try:
                    scoring[engine_key] = float(settings[sleeper_key])
                except (TypeError, ValueError):
                    pass

        roster_slots = {
            "QB": 0,
            "RB": 0,
            "WR": 0,
            "TE": 0,
            "FLEX": 0,
            "SUPERFLEX": 0,
            "BENCH": 0,
            "K": 0,
            "DST": 0,
        }
        positions = league.get("roster_positions") or settings.get("roster_positions") or []
        for code in positions:
            key = _SLOT_MAP.get(str(code).upper())
            if key:
                roster_slots[key] += 1

        teams_count = int(settings.get("num_teams") or len(self._rosters or []) or 12)
        if teams_count < 2:
            teams_count = 12

        return {
            "name": league.get("name") or "Sleeper League",
            "scoring": scoring,
            "roster_slots": roster_slots,
            "teams_count": teams_count,
        }

    def fetch_normalized_rosters(self) -> list[dict[str, Any]]:
        """Return normalized ``{team_index, team_name, players}`` rosters.

        Used by ``SYNC_PLATFORM_LEAGUE`` so the UI can persist real team names
        and roster contents without an additional platform-specific mapping.
        Player name/position is left ``None`` here because Sleeper rosters only
        carry player IDs; resolving names requires the (large) player index.
        """
        self.fetch_rosters()
        rosters: list[dict[str, Any]] = []
        for index, roster in enumerate(self._rosters or []):
            metadata = roster.get("metadata") or {}
            name = (
                metadata.get("team_name")
                or roster.get("display_name")
                or roster.get("owner_id")
                or f"Team {index + 1}"
            )
            players = [
                {"player_id": str(pid), "name": None, "position": None}
                for pid in (roster.get("players") or [])
            ]
            rosters.append(
                {"team_index": index, "team_name": str(name), "players": players}
            )
        return rosters

    # ------------------------------------------------------------------
    # Live stream
    # ------------------------------------------------------------------
    async def stream_picks(
        self,
        *,
        draft_ws_url: str = SLEEPER_DRAFT_WS,
        poll_interval: float = 3.0,
        initial_picks: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield normalized picks as they happen.

        Uses the Sleeper draft WebSocket when available and transparently
        falls back to REST polling every ``poll_interval`` seconds if the
        socket cannot be established. Existing picks are yielded first when
        ``initial_picks`` is true.
        """
        if initial_picks:
            for pick in self.normalize_picks():
                yield pick

        try:
            import websockets  # local import: optional at runtime

            async for pick in self._stream_via_websocket(websockets, draft_ws_url):
                yield pick
        except Exception:
            # Failover: REST polling on the 3s cadence (see .clinerules).
            async for pick in self._stream_via_polling(poll_interval):
                yield pick

    async def _stream_via_websocket(self, websockets, url: str) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to the Sleeper draft WebSocket and normalize events.

        Any connection error propagates to :meth:`stream_picks`, which catches
        it and fails over to REST polling. ``asyncio.CancelledError`` is not an
        ``Exception`` subclass, so task cancellation passes through untouched.
        """
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({"type": "draft", "draft_id": self.draft_id}))
            known: set[str] = set()
            async for message in ws:
                data = json.loads(message)
                event = data.get("type") or data.get("event")
                payload = data.get("data") or data
                if event not in ("pick", "pick_made", "draft_pick", None):
                    continue
                pick = payload if isinstance(payload, dict) else {}
                normalized = self.normalize_pick(pick)
                if not normalized:
                    continue
                key = f"{normalized['pick_number']}:{normalized['player_id']}"
                if key in known:
                    continue
                known.add(key)
                yield normalized

    async def _stream_via_polling(self, interval: float) -> AsyncIterator[dict[str, Any]]:
        """Poll the REST picks endpoint, yielding only newly seen picks."""
        known: set[str] = set()
        while True:
            for normalized in self.normalize_picks():
                key = f"{normalized['pick_number']}:{normalized['player_id']}"
                if key in known:
                    continue
                known.add(key)
                yield normalized
            await asyncio.sleep(interval)


__all__ = ["SleeperAdapter"]