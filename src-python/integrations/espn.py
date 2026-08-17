"""ESPN platform adapter.

Wraps the ``espn_api`` package (installed as ``espn-api``) to ingest ESPN
league settings, rosters, and draft picks. ESPN fantasy endpoints require two
authentication cookies:

* ``SWID``     -- the encrypted "SWID" identity cookie.
* ``espn_s2``  -- the short-lived ``espn_s2`` session cookie.

These are passed to the adapter (either as explicit values or via the
``ESPN_SWID`` / ``ESPN_S2`` environment variables) and forwarded to the SDK.

The SDK's draft support is limited, so this adapter also exposes a direct
``requests``-based fallback for the private ``/draft/recap`` endpoints.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .normalizer import PlayerNormalizer

# Map ESPN position abbreviations to the engine's positional vocabulary.
_POSITION_MAP: dict[str, Optional[str]] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "K": "K",
    "D/ST": "DST",
    "DST": "DST",
    "DT": "DST",
    "DEF": "DST",
    "FLEX": None,  # resolved per-position later
}


class EspnAdapter:
    """ESPN league ingestion via ``espn_api`` (SWID + espn_s2 auth)."""

    def __init__(
        self,
        league_id: int,
        *,
        year: Optional[int] = None,
        swid: Optional[str] = None,
        espn_s2: Optional[str] = None,
    ) -> None:
        self.league_id = league_id
        self.year = year or int(os.environ.get("ESPN_YEAR", "2024"))
        self.swid = swid or os.environ.get("ESPN_SWID")
        self.espn_s2 = espn_s2 or os.environ.get("ESPN_S2")
        self.normalizer = PlayerNormalizer()
        self._league: Any = None
        self._teams: Optional[list[Any]] = None

    # ------------------------------------------------------------------
    # SDK plumbing (lazy import keeps the adapter optional at runtime)
    # ------------------------------------------------------------------
    def _get_league(self) -> Any:
        if self._league is None:
            try:
                from espn_api.football import League  # type: ignore
            except Exception as exc:  # pragma: no cover - env dependent
                raise RuntimeError(f"espn-api unavailable: {exc}") from exc

            self._league = League(
                league_id=self.league_id,
                year=self.year,
                swid=self.swid,
                espn_s2=self.espn_s2,
            )
        return self._league

    # ------------------------------------------------------------------
    # League data
    # ------------------------------------------------------------------
    def fetch_teams(self) -> list[Any]:
        """Return ESPN ``Team`` objects for the league."""
        if self._teams is None:
            self._teams = list(self._get_league().teams or [])
        return self._teams

    def fetch_settings(self) -> dict[str, Any]:
        """Return ESPN league settings."""
        league = self._get_league()
        return dict(getattr(league, "settings", None) or {})

    def to_league_config(self, *, name: Optional[str] = None) -> dict[str, Any]:
        """Map ESPN settings to the engine ``LeagueConfig`` schema."""
        settings = self.fetch_settings()
        teams = self.fetch_teams()

        scoring = {
            # ESPN settings already store points-per-yard directly, matching
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
            "name": name or f"ESPN League {self.league_id}",
            "scoring": scoring,
            "roster_slots": roster_slots,
            "teams_count": len(teams) or 12,
        }

    def fetch_rosters(self) -> list[dict[str, Any]]:
        """Return a normalized list of rosters keyed by team."""
        teams = self.fetch_teams()
        rosters: list[dict[str, Any]] = []
        for index, team in enumerate(teams):
            roster: dict[str, Any] = {
                "team_index": index,
                "team_name": getattr(team, "team_name", None) or f"Team {index + 1}",
                "players": [],
            }
            for player in getattr(team, "roster", []) or []:
                roster["players"].append(
                    {
                        "player_id": str(getattr(player, "playerId", None) or ""),
                        "name": getattr(player, "name", None),
                        "position": _POSITION_MAP.get(
                            str(getattr(player, "position", "")).upper(),
                            str(getattr(player, "position", "")).upper(),
                        ),
                    }
                )
            rosters.append(roster)
        return rosters

    # ------------------------------------------------------------------
    # Draft picks (direct REST fallback, since espn_api lacks full draft API)
    # ------------------------------------------------------------------
    def fetch_draft_picks(self) -> list[dict[str, Any]]:
        """Fetch ESPN draft recap picks via the private REST endpoint."""
        import requests  # local import: optional at runtime

        if not self.swid or not self.espn_s2:
            raise ValueError("ESPN draft recap requires SWID and espn_s2 cookies")

        url = (
            "https://fantasy.espn.com/apis/v3/games/ffl/seasons/"
            f"{self.year}/segments/0/leagues/{self.league_id}?view=mDraftDetail"
        )
        response = requests.get(
            url,
            cookies={"SWID": self.swid, "espn_s2": self.espn_s2},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        draft = (payload.get("draftDetail") or {}).get("draft")
        picks = (draft or {}).get("picks") or []
        return [dict(p) for p in picks if isinstance(p, dict)]

    def normalize_pick(self, pick: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Normalize one raw ESPN draft pick into an engine-ready dict."""
        player = pick.get("player") or {}
        player_id = str(
            player.get("playerId") or pick.get("playerId") or player.get("id") or ""
        )
        name = (
            player.get("fullName")
            or player.get("name")
            or pick.get("playerName")
            or ""
        )

        if not player_id:
            return None

        position = None
        pos_code = player.get("defaultPosition") or pick.get("position")
        if pos_code is not None:
            position = _POSITION_MAP.get(
                str(pos_code).upper(), str(pos_code).upper()
            )

        # Resolve first so a pre-seeded cross-platform mapping wins; only
        # register a fresh canonical record when the identity is unknown.
        resolved = self.normalizer.resolve(
            platform="espn",
            platform_id=player_id,
            name=str(name) or None,
        )
        if resolved is None:
            self.normalizer.register(
                player_id=player_id,
                name=str(name) or player_id,
                position=position,
                platform="espn",
                platform_id=player_id,
            )

        return self.normalizer.normalize_pick(
            {
                "player_id": player_id,
                "name": name,
                "position": position,
                "team_index": int(pick.get("teamId") or pick.get("team_index") or 0),
                "round": pick.get("roundNumber") or pick.get("round"),
                "pick_number": pick.get("overallPickNumber")
                or pick.get("overall_pick")
                or pick.get("pickNumber"),
                "timestamp": pick.get("timestamp"),
            },
            platform="espn",
        )

    def normalize_picks(self) -> list[dict[str, Any]]:
        """Fetch and normalize all ESPN draft picks."""
        raw = self.fetch_draft_picks()
        return list(filter(None, (self.normalize_pick(p) for p in raw)))


__all__ = ["EspnAdapter"]