"""Cross-platform player identity normalization.

Each platform adapter (Sleeper, ESPN, Yahoo) reports picks keyed by its own
native player ID and display name. This module collapses those identities into
a single global player dictionary so the analytics engine -- which keys
``DraftPickMadePayload`` on a canonical ``player_id`` -- stays consistent no
matter which platform produced the event.

The normalizer is intentionally dependency-free (only pydantic, which the
engine already requires) so it can run inline inside the sidecar without
importing any of the optional platform SDKs.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class NormalizedPlayer(BaseModel):
    """A player identity canonicalized across platforms.

    ``player_id`` is the global key used by the engine. ``platform_ids`` maps a
    platform name (``"sleeper"``, ``"espn"``, ``"yahoo"``) to that platform's
    native ID so a pick reported by any adapter can be resolved to the same
    player.
    """

    player_id: str
    name: str
    position: Optional[str] = None
    team: Optional[str] = None
    platform_ids: dict[str, str] = Field(default_factory=dict)


class PlayerNormalizer:
    """Global player registry built from platform adapter outputs.

    Registration is idempotent: adding the same platform ID twice updates the
    existing record rather than creating a duplicate. Resolution prefers an
    exact canonical ``player_id`` match, then any platform ID, then a
    normalized-name fallback so picks reported with loose metadata still land
    in the same identity space.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, NormalizedPlayer] = {}
        self._by_platform: dict[tuple[str, str], str] = {}
        self._by_name: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(
        self,
        *,
        player_id: str,
        name: str,
        position: Optional[str] = None,
        team: Optional[str] = None,
        platform: Optional[str] = None,
        platform_id: Optional[str] = None,
    ) -> NormalizedPlayer:
        """Create or update a global player record.

        Returns the (possibly newly created) canonical record. If ``platform``
        and ``platform_id`` are supplied, the mapping is recorded so future
        ``resolve`` calls can translate that native ID back to ``player_id``.
        """
        player = self._by_id.get(player_id)
        if player is None:
            player = NormalizedPlayer(
                player_id=player_id,
                name=name,
                position=position,
                team=team,
            )
            self._by_id[player_id] = player
        else:
            if name and player.name != name:
                player.name = name
            if position and player.position is None:
                player.position = position
            if team and player.team is None:
                player.team = team

        if platform and platform_id:
            player.platform_ids[platform] = platform_id
            self._by_platform[(platform, str(platform_id))] = player_id

        self._by_name[_name_key(name)] = player_id
        return player

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve(
        self,
        *,
        player_id: Optional[str] = None,
        platform: Optional[str] = None,
        platform_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[NormalizedPlayer]:
        """Resolve whatever identity material is available to a global record."""
        if player_id and player_id in self._by_id:
            return self._by_id[player_id]

        if platform and platform_id:
            key = (platform, str(platform_id))
            if key in self._by_platform:
                return self._by_id[self._by_platform[key]]

        if name:
            key = _name_key(name)
            if key in self._by_name:
                return self._by_id[self._by_name[key]]

        return None

    def normalize_pick(
        self,
        payload: dict[str, Any],
        *,
        platform: str = "unknown",
    ) -> Optional[dict[str, Any]]:
        """Normalize a platform pick payload into an engine-ready dict.

        The input may use platform-native field names (e.g. Sleeper
        ``player_id`` -> ``player_id``, ESPN ``playerId`` -> ``player_id``,
        Yahoo ``player_key`` -> ``player_id``). Returns a dict shaped like
        ``DraftPickMadePayload``, or ``None`` when the payload is unusable.
        """
        player_id = _first_str(payload, "player_id", "playerId", "playerID", "player_key", "playerKey")
        platform_id = _first_str(payload, "player_id", "playerId", "id", "player_key")
        name = _first_str(payload, "name", "player_name", "playerName", "full_name", "fullName")
        position = _first_str(payload, "position", "pos", "slot")
        team_index = _first_int(payload, "team_index", "teamIndex", "draft_slot", "draftSlot", "roster_id", "rosterId")
        round_ = _first_int(payload, "round", "rnd")
        pick_number = _first_int(
            payload, "pick_number", "pickNumber", "overall_pick", "overallPick", "pick_no", "pickNo"
        )

        if team_index is None or pick_number is None:
            return None

        resolved = self.resolve(
            player_id=player_id,
            platform=platform,
            platform_id=platform_id,
            name=name,
        )

        canonical_id = resolved.player_id if resolved else (player_id or name or str(platform_id or ""))

        return {
            "pick_number": pick_number,
            "round": round_ or 1,
            "team_index": team_index,
            "player_id": canonical_id,
            "position": (resolved.position if resolved else None) or position,
            "timestamp": _first_float(payload, "timestamp", "picked_at", "pickedAt", "time"),
        }

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Serialize the registry (e.g. for the integration tests)."""
        return {
            player_id: {
                "player_id": p.player_id,
                "name": p.name,
                "position": p.position,
                "team": p.team,
                "platform_ids": dict(p.platform_ids),
            }
            for player_id, p in self._by_id.items()
        }

    def __len__(self) -> int:
        return len(self._by_id)


def _name_key(name: str) -> str:
    """Normalize a display name for case/punctuation-insensitive matching."""
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch.isspace()).strip()


def _first_str(payload: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            # Also check a lower-cased walk for loose adapters.
            value = payload.get(key.lower())
        if value is not None and value != "":
            return str(value).strip()
    return None


def _first_int(payload: dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            value = payload.get(key.lower())
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _first_float(payload: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            value = payload.get(key.lower())
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


__all__ = ["NormalizedPlayer", "PlayerNormalizer"]