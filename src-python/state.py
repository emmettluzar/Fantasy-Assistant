"""Live draft state manager bridging the WebSocket server and engine.

This module owns the mutable state for a single draft session:

* the active :class:`~engine.models.LeagueConfig`,
* the user's drafting slot (``user_team_index``),
* the enriched projection pool (built once from ``nfl_data_py`` or the
  offline synthetic fallback),
* every pick ingested so far, and the per-position / per-team tallies derived
  from them.

Every mutating operation is designed to run in well under 50ms so the server
can respond synchronously on the hot ``DRAFT_PICK_MADE`` path.
"""

from __future__ import annotations

from collections import defaultdict

from engine.dvorp import compute_all_dvorp, compute_baselines
from engine.models import DraftPick, LeagueConfig, PlayerProjection, Position
from engine.probability import (
    DecisionContext,
    compute_player_dvorp_map,
    rank_decisions,
)
from engine.projections import build_projection_pool, filter_available

# Pre-shuffled seed used when a client does not supply one; keeps responses
# reproducible between the Python server and its test harness.
DEFAULT_SEED = 42


class DraftState:
    """Single-draft session state and computation facade."""

    def __init__(self) -> None:
        self.config: LeagueConfig = LeagueConfig.full_ppr()
        self.user_team_index: int = 0
        self.allow_network: bool = False
        self.pool: list[PlayerProjection] = []
        self._by_id: dict[str, PlayerProjection] = {}

        self.drafted_ids: set[str] = set()
        self.drafted_positions: list[Position] = []
        self.picks: list[DraftPick] = []

        # User roster bookkeeping for roster-need and bye-overlap factors.
        self.user_owned: dict[Position, int] = defaultdict(int)
        self.user_starters_bye: dict[int, int] = defaultdict(int)
        self.user_starter_count: int = 0

        # Initialized on first sync so an un-configured session never errors.
        self._rebuild_pool()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def sync_config(self, config: LeagueConfig, user_team_index: int, allow_network: bool) -> None:
        """Apply a new league configuration and rebuild the projection pool.

        Per the spec, ``SYNC_LEAGUE_CONFIG`` re-initializes the live draft
        board because scoring/roster changes invalidate prior value baselines.
        """
        self.config = config
        self.user_team_index = user_team_index
        self.allow_network = allow_network
        self.reset(keep_config=True)

    def reset(self, *, keep_config: bool = True) -> None:
        """Clear all draft state; optionally restore the default config."""
        if not keep_config:
            self.config = LeagueConfig.full_ppr()
            self.user_team_index = 0
            self.allow_network = False

        self.drafted_ids.clear()
        self.drafted_positions.clear()
        self.picks.clear()
        self.user_owned = defaultdict(int)
        self.user_starters_bye = defaultdict(int)
        self.user_starter_count = 0

        self._rebuild_pool()

    def _rebuild_pool(self) -> None:
        """(Re)build the scoring-aware projection pool for the active config."""
        self.pool = build_projection_pool(
            self.config,
            allow_network=self.allow_network,
            seed=DEFAULT_SEED,
        )
        self._by_id = {p.player_id: p for p in self.pool}

    # ------------------------------------------------------------------
    # Computation helpers
    # ------------------------------------------------------------------
    def remaining(self) -> list[PlayerProjection]:
        """Currently undrafted players."""
        return filter_available(self.pool, self.drafted_ids)

    def drafted_by_pos(self) -> dict[Position, int]:
        """League-wide count of drafted players per position."""
        return self._count_positions(self.drafted_positions)

    @staticmethod
    def _count_positions(positions: list[Position]) -> dict[Position, int]:
        counts: dict[Position, int] = defaultdict(int)
        for position in positions:
            counts[position] += 1
        return dict(counts)

    def dvorp_for_remaining(self) -> tuple[list, dict[str, float]]:
        """Compute DVORP for the remaining pool, returning results and a map.

        Returns ``(results, player_id -> dvorp)``. The DVORP engine recomputes
        replacement baselines dynamically from the currently undrafted pool.
        """
        results = compute_all_dvorp(
            self.config, self.remaining(), self.drafted_by_pos()
        )
        return results, compute_player_dvorp_map(results)

    def baselines_serialized(self) -> dict[str, float]:
        """Serializable replacement baseline per skill position."""
        baseline = compute_baselines(self.config, self.remaining(), self.drafted_by_pos())
        return baseline.baselines

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def ingest_pick(self, payload) -> DraftPick:
        """Record a normalized pick and update dynamic baselines.

        Raises :class:`ValueError` if the pick is malformed (unknown player,
        duplicate pick number, or team index out of range).
        """
        if payload.team_index < 0 or payload.team_index >= self.config.teams_count:
            raise ValueError(
                f"team_index {payload.team_index} out of range "
                f"[0, {self.config.teams_count - 1}]"
            )

        player = self._by_id.get(payload.player_id)
        if player is None:
            raise ValueError(f"unknown player_id: {payload.player_id}")

        if any(p.pick_number == payload.pick_number for p in self.picks):
            raise ValueError(f"duplicate pick_number: {payload.pick_number}")

        if player.player_id in self.drafted_ids:
            raise ValueError(f"player already drafted: {payload.player_id}")

        position = payload.position or player.position
        fp = (
            payload.fantasy_points
            if payload.fantasy_points is not None
            else player.fantasy_points
        )
        pick = DraftPick(
            pick_number=payload.pick_number,
            round=payload.round,
            team_index=payload.team_index,
            player_id=player.player_id,
            position=position,
            fantasy_points=fp,
            timestamp=payload.timestamp,
        )

        self.drafted_ids.add(player.player_id)
        self.drafted_positions.append(position)
        self.picks.append(pick)

        if payload.team_index == self.user_team_index:
            self.user_owned[position] += 1
            if self.user_starter_count < self.config.roster_slots.total_starters():
                self.user_starter_count += 1
                self.user_starters_bye[player.bye_week] += 1

        return pick

    def compute_user_next_pick(self) -> float:
        """Return the user's next pick strictly after the current one.

        Snake-order picks for team ``t`` (0-based) in round ``r`` (1-based):

        * odd rounds:  ``(r - 1) * teams + (t + 1)``
        * even rounds: ``(r - 1) * teams + (teams - t)``
        """
        teams = self.config.teams_count
        current = self.picks[-1].pick_number if self.picks else 0
        rounds = self.config.total_rounds()
        later: list[int] = []
        t = self.user_team_index + 1
        for rnd in range(1, rounds + 1):
            if rnd % 2 == 1:
                pick = (rnd - 1) * teams + t
            else:
                pick = (rnd - 1) * teams + (teams - t + 1)
            if pick > current:
                later.append(pick)
        return float(min(later)) if later else 0.0

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------
    def get_recommendations(self, payload) -> dict:
        """Return the top available players ranked by ``U_i(t)``.

        The payload may override ``user_team_index``, ``r_next``, and the
        return ``limit``; otherwise the session values are used.
        """
        user_index = (
            payload.user_team_index
            if payload.user_team_index is not None
            else self.user_team_index
        )
        r_next = (
            payload.r_next if payload.r_next is not None else self.compute_user_next_pick()
        )
        limit = payload.limit

        remaining = self.remaining()
        _, dvorp_map = self.dvorp_for_remaining()

        context = DecisionContext(
            dvorp=dvorp_map,
            roster_slots=self.config.roster_slots,
            owned=dict(self.user_owned),
            starters_bye=dict(self.user_starters_bye),
            r_next=r_next,
        )
        ranked = rank_decisions(remaining, context, dvorp_by_id=dvorp_map)

        recommendations = []
        for choice in ranked[:limit]:
            player = self._by_id[choice.player_id]
            recommendations.append(
                {
                    "player_id": choice.player_id,
                    "name": player.name,
                    "position": choice.position,
                    "team": player.team,
                    "adp": player.adp,
                    "bye_week": player.bye_week,
                    "fantasy_points": player.fantasy_points,
                    "dvorp": choice.dvorp,
                    "p_mb": choice.p_mb,
                    "r_need": choice.r_need,
                    "p_bye": choice.p_bye,
                    "utility": choice.utility,
                }
            )

        return {
            "user_team_index": user_index,
            "r_next": r_next,
            "available_count": len(remaining),
            "recommendations": recommendations,
        }

    # ------------------------------------------------------------------
    # Snapshots (for RESET_DRAFT / debugging)
    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        """Serializable board summary."""
        return {
            "config": self.config.model_dump(),
            "user_team_index": self.user_team_index,
            "drafted_count": len(self.drafted_ids),
            "available_count": len(self.remaining()),
            "picks": [p.model_dump() for p in self.picks],
            "user_owned": dict(self.user_owned),
        }


__all__ = ["DraftState", "DEFAULT_SEED"]