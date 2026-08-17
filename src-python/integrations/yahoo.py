"""Yahoo platform adapter.

Wraps ``yfpy`` with OAuth 2.0 to ingest Yahoo league settings, rosters, and
draft picks. Authentication is handled by ``yfpy``'s ``Data`` class, which
reads OAuth credentials from the environment (or a JSON credentials file) and
manages token refresh transparently.

The adapter supports either:

* a pre-authenticated ``yfpy`` ``Data`` instance passed by the caller, or
* constructing one from ``YFPY_AUTH_DIR`` / ``YFPY_CONSUMER_KEY`` /
  ``YFPY_CONSUMER_SECRET`` environment variables.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .normalizer import PlayerNormalizer

# Yahoo position abbreviations -> engine positional vocabulary.
_POSITION_MAP: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "K": "K",
    "DEF": "DST",
    "D": "DST",
    "DST": "DST",
    "W/R/T": "FLEX",
    "Q/W/R/T": "SUPERFLEX",
    "BN": "BENCH",
}


class YahooAdapter:
    """Yahoo league ingestion via ``yfpy`` (OAuth 2.0)."""

    def __init__(
        self,
        league_id: int,
        *,
        game_key: Optional[str] = None,
        season: Optional[int] = None,
        data: Any = None,
    ) -> None:
        self.league_id = league_id
        self.game_key = game_key or os.environ.get("YFPY_GAME_KEY", "nfl")
        self.season = season or int(os.environ.get("YFPY_SEASON", "2024"))
        self._data = data
        self.normalizer = PlayerNormalizer()
        self._league: Any = None

    # ------------------------------------------------------------------
    # SDK plumbing (lazy import keeps the adapter optional at runtime)
    # ------------------------------------------------------------------
    def _get_data(self) -> Any:
        if self._data is None:
            try:
                from yfpy import Data  # type: ignore
            except Exception as exc:  # pragma: no cover - env dependent
                raise RuntimeError(f"yfpy unavailable: {exc}") from exc

            # yfpy reads ``YFPY_*`` env vars for the OAuth flow by default.
            self._data = Data()
        return self._data

    def _get_league(self) -> Any:
        if self._league is None:
            data = self._get_data()
            self._league = data.get_league(self.league_id, game_code=self.game_key)
        return self._league

    # ------------------------------------------------------------------
    # League data
    # ------------------------------------------------------------------
    def fetch_teams(self) -> list[Any]:
        """Return Yahoo team objects for the league."""
        league = self._get_league()
        teams = getattr(league, "teams", None) or []
        # yfpy returns a dict keyed by team key in some versions.
        if isinstance(teams, dict):
            return list(teams.values())
        return list(teams)

    def fetch_settings(self) -> dict[str, Any]:
        """Return Yahoo league settings."""
        league = self._get_league()
        settings = getattr(league, "settings", None)
        if settings is None:
            return {}
        raw = getattr(settings, "raw", None) or vars(settings)
        if isinstance(raw, dict):
            return dict(raw)
        return {
            key: getattr(settings, key)
            for key in dir(settings)
            if not key.startswith("_")
        }

    def to_league_config(self, *, name: Optional[str] = None) -> dict[str, Any]:
        """Map Yahoo settings to the engine ``LeagueConfig`` schema."""
        settings = self.fetch_settings()
        teams = self.fetch_teams()

        scoring = {
            # Yahoo settings already store points-per-yard directly, matching
            # the engine's `pass_yd` / `rush_yd` / `rec_yd` fields.
            "pass_yd": float(settings.get("passing_yards") or 0.04),
            "pass_td": float(settings.get("passing_td") or 4.0),
            "pass_int": float(settings.get("passing_int") or -2.0),
            "rush_yd": float(settings.get("rushing_yards") or 0.1),
            "rush_td": float(settings.get("rushing_td") or 6.0),
            "rec": float(settings.get("receiving_rec") or 0.0),
            "rec_yd": float(settings.get("receiving_yards") or 0.1),
            "rec_td": float(settings.get("receiving_td") or 6.0),
            "te_rec_bonus": float(settings.get("receiving_te_rec") or 0.0),
            "fumble_lost": float(settings.get("fumble_lost") or -2.0),
            "two_pt": float(settings.get("two_pt") or 2.0),
        }

        roster_slots = {
            "QB": int(settings.get("starting_qb") or 1),
            "RB": int(settings.get("starting_rb") or 2),
            "WR": int(settings.get("starting_wr") or 2),
            "TE": int(settings.get("starting_te") or 1),
            "FLEX": int(settings.get("starting_flex") or 1),
            "SUPERFLEX": int(settings.get("starting_superflex") or 0),
            "BENCH": int(settings.get("bench") or 6),
            "K": int(settings.get("starting_k") or 0),
            "DST": int(settings.get("starting_dst") or 0),
        }

        return {
            "name": name or settings.get("name") or f"Yahoo League {self.league_id}",
            "scoring": scoring,
            "roster_slots": roster_slots,
            "teams_count": len(teams) or 12,
        }

    def fetch_rosters(self) -> list[dict[str, Any]]:
        """Return a normalized list of rosters keyed by team."""
        rosters: list[dict[str, Any]] = []
        for index, team in enumerate(self.fetch_teams()):
            roster: dict[str, Any] = {
                "team_index": index,
                "team_name": getattr(team, "name", None) or f"Team {index + 1}",
                "players": [],
            }
            rosters.append(roster)
            for player in getattr(team, "roster", None) or []:
                roster["players"].append(
                    {
                        "player_id": str(getattr(player, "player_key", None) or ""),
                        "name": str(
                            (getattr(player, "name", None) or {}).get("full")
                            or getattr(player, "player_key", None)
                            or ""
                        ),
                        "position": _POSITION_MAP.get(
                            str(getattr(player, "display_position", "")).upper(),
                            str(getattr(player, "display_position", "")).upper(),
                        ),
                    }
                )
        return rosters

    # ------------------------------------------------------------------
    # Draft picks
    # ------------------------------------------------------------------
    def fetch_draft_results(self) -> list[dict[str, Any]]:
        """Fetch Yahoo draft results via yfpy."""
        league = self._get_league()
        results = getattr(league, "draft_results", None) or []
        if isinstance(results, dict):
            results = list(results.values())
        return [dict(r) for r in results if isinstance(r, dict)]

    def normalize_pick(self, pick: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Normalize one raw Yahoo draft result into an engine-ready dict."""
        player_key = str(
            pick.get("player_key")
            or pick.get("playerKey")
            or pick.get("player_id")
            or ""
        )

        player = pick.get("player")
        if isinstance(player, dict):
            name = player.get("full_name") or player.get("name") or ""
            position = player.get("display_position") or player.get("position")
        else:
            name = pick.get("player_name") or pick.get("playerName") or ""
            position = pick.get("position")

        if not player_key:
            return None

        if position:
            position = _POSITION_MAP.get(str(position).upper(), str(position).upper())

        # Resolve first so a pre-seeded cross-platform mapping wins; only
        # register a fresh canonical record when the identity is unknown.
        resolved = self.normalizer.resolve(
            platform="yahoo",
            platform_id=player_key,
            name=str(name) or None,
        )
        if resolved is None:
            self.normalizer.register(
                player_id=player_key,
                name=str(name) or player_key,
                position=position,
                platform="yahoo",
                platform_id=player_key,
            )

        return self.normalizer.normalize_pick(
            {
                "player_id": player_key,
                "name": name,
                "position": position,
                "team_index": int(pick.get("team_index") or pick.get("team_no") or 0),
                "round": pick.get("round") or 1,
                "pick_number": pick.get("pick") or pick.get("pick_number"),
                "timestamp": pick.get("timestamp"),
            },
            platform="yahoo",
        )

    def normalize_picks(self) -> list[dict[str, Any]]:
        """Fetch and normalize all Yahoo draft results."""
        raw = self.fetch_draft_results()
        return list(filter(None, (self.normalize_pick(p) for p in raw)))


__all__ = ["YahooAdapter"]