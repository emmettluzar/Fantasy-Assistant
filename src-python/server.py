"""Local WebSocket IPC server for the Fantasy Draft Assistant.

Listens on ``ws://127.0.0.1:8080`` (see ``IPC_PROTOCOL.md``) and handles the
four message types:

* ``SYNC_LEAGUE_CONFIG`` -- applies a new :class:`LeagueConfig`.
* ``DRAFT_PICK_MADE``   -- ingests a pick, then returns refreshed baselines.
* ``GET_RECOMMENDATIONS`` -- returns the top available players by ``U_i(t)``.
* ``RESET_DRAFT``       -- clears the live draft board.
* ``PICK_UPDATE``       -- server-push broadcast to every other connected
  client after a pick is ingested (so a browser-extension pick instantly
  refreshes the desktop board).

The server only uses the standard library plus the ``websockets`` package, so
it runs inside the same isolated virtual environment that powers the engine.
The envelope format is::

    {"type": "<TYPE>", "payload": { ... }, "request_id": "<id>"}

Run directly (venv already active)::

    python src-python/server.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
from typing import Any, Optional

from websockets.asyncio.server import serve

from engine.models import PlayerProjection, Position
from inseason.optimizer import RosterPlayer as OptimizerRosterPlayer, optimize_lineup
from inseason.trades import evaluate_trade
from inseason.waivers import calculate_faab_bids
from protocol import (
    CalculateFaabBidsPayload,
    DraftPickMadePayload,
    EvaluateTradePayload,
    GetRecommendationsPayload,
    OptimizeLineupPayload,
    ResetDraftPayload,
    RosterPlayerPayload,
    SyncLeagueConfigPayload,
)
from state import DraftState

logger = logging.getLogger("fda.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

# Message types handled by this server.
TYPE_SYNC = "SYNC_LEAGUE_CONFIG"
TYPE_PICK = "DRAFT_PICK_MADE"
TYPE_RECOMMEND = "GET_RECOMMENDATIONS"
TYPE_RESET = "RESET_DRAFT"
# Server-push frame type broadcast to other connected clients after a pick.
TYPE_PICK_UPDATE = "PICK_UPDATE"
# In-season automation handlers (Phase 5).
TYPE_OPTIMIZE = "OPTIMIZE_LINEUP"
TYPE_EVALUATE_TRADE = "EVALUATE_TRADE"
TYPE_FAAB = "CALCULATE_FAAB_BIDS"


def _error(message: str, code: str = "BAD_REQUEST") -> dict:
    return {"ok": False, "error": message, "code": code}


def _response(request_id: Optional[str], data: Any) -> str:
    """Serialize a response envelope to JSON text."""
    return json.dumps(
        {
            "type": "RESPONSE",
            "request_id": request_id or "",
            "payload": data,
        }
    )


class DraftSession:
    """Routes frames to a single shared :class:`DraftState`.

    Concurrency note: ``asyncio`` handlers run cooperatively on one thread, so
    the mutable state has no data races. Every handler is synchronous and fast
    (< 50ms), which keeps the event loop responsive.
    """

    def __init__(self) -> None:
        self.state = DraftState()
        # Connected clients, used to fan out PICK_UPDATE broadcasts. The asyncio
        # handlers run cooperatively on one thread, so the set needs no lock.
        self.clients: set = set()

    def handle(self, message: str) -> str:
        """Dispatch one inbound frame and return the outbound JSON response.

        Broadcast frames are computed but not transmitted here; the async
        connection loop uses :meth:`handle_frame` instead so it can fan them
        out to every other connected client.
        """
        response, _ = self.handle_frame(message)
        return response

    def handle_frame(self, message: str) -> tuple[str, list[str]]:
        """Dispatch a frame; return ``(response_text, broadcast_frames)``."""
        try:
            frame = json.loads(message)
        except json.JSONDecodeError as exc:
            return _response(None, _error(f"invalid JSON: {exc}")), []

        if not isinstance(frame, dict):
            return _response(None, _error("frame must be a JSON object")), []

        msg_type = frame.get("type")
        if not isinstance(msg_type, str):
            return _response(None, _error("missing or invalid 'type'")), []

        payload = frame.get("payload", {})
        if not isinstance(payload, dict):
            return _response(None, _error("'payload' must be a JSON object")), []

        request_id = frame.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            return _response(None, _error("'request_id' must be a string")), []

        handler = self._HANDLERS.get(msg_type)
        if handler is None:
            return _response(request_id, _error(f"unknown message type: {msg_type}")), []

        try:
            data = handler(self, payload)
            broadcasts: list[str] = []
            if msg_type == TYPE_PICK:
                broadcasts = self._pick_update_frames(data)
            return _response(request_id, {"ok": True, "data": data}), broadcasts
        except ValueError as exc:
            return _response(request_id, _error(str(exc))), []
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("unhandled error handling %s", msg_type)
            return _response(request_id, _error(str(exc), code="INTERNAL_ERROR")), []

    def _pick_update_frames(self, data: dict) -> list[str]:
        """Build a ``PICK_UPDATE`` broadcast frame for a freshly ingested pick.

        The payload carries the echo that ``DRAFT_PICK_MADE`` returns plus a
        full ``BoardSnapshot`` so a desktop client can apply the change without
        a follow-up request.
        """
        push = {
            "type": TYPE_PICK_UPDATE,
            "request_id": "",
            "payload": {
                "pick": data["pick"],
                "available_count": data["available_count"],
                "baselines": data["baselines"],
                "dvorp_updated": data["dvorp_updated"],
                "snapshot": self.state.snapshot(),
            },
        }
        return [json.dumps(push)]

    async def broadcast(self, frames: list[str], *, exclude=None) -> None:
        """Fan out pre-serialized frames to connected clients.

        ``exclude`` is skipped so the sender of an event does not receive its
        own notification (it already got the correlated ``RESPONSE``).
        """
        if not frames:
            return
        stale = []
        for ws in self.clients:
            if ws is exclude:
                continue
            try:
                for frame in frames:
                    await ws.send(frame)
            except Exception:  # pragma: no cover - defensive
                stale.append(ws)
        for ws in stale:
            self.clients.discard(ws)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _handle_sync(self, payload: dict) -> dict:
        sync = SyncLeagueConfigPayload.model_validate(payload)
        self.state.sync_config(
            config=sync.to_league_config(),
            user_team_index=sync.user_team_index,
            allow_network=sync.allow_network,
        )
        return self.state.snapshot()

    def _handle_pick(self, payload: dict) -> dict:
        pick = DraftPickMadePayload.model_validate(payload)
        recorded = self.state.ingest_pick(pick)
        # The refreshed replacement baselines are returned immediately so the
        # caller can update its board without a second round-trip.
        return {
            "pick": {
                "pick_number": recorded.pick_number,
                "round": recorded.round,
                "team_index": recorded.team_index,
                "player_id": recorded.player_id,
                "position": recorded.position,
                "fantasy_points": recorded.fantasy_points,
            },
            "available_count": len(self.state.remaining()),
            "baselines": {
                "replacements": self.state.baselines_serialized(),
            },
            "dvorp_updated": True,
        }

    def _handle_recommend(self, payload: dict) -> dict:
        rec = GetRecommendationsPayload.model_validate(payload)
        return self.state.get_recommendations(rec)

    def _handle_reset(self, payload: dict) -> dict:
        reset = ResetDraftPayload.model_validate(payload)
        self.state.reset(keep_config=reset.keep_config)
        return self.state.snapshot()

    def _handle_optimize_lineup(self, payload: dict) -> dict:
        req = OptimizeLineupPayload.model_validate(payload)
        roster = [self._to_optimizer_player(p) for p in req.roster]
        result = optimize_lineup(self.state.config, roster)
        return result.to_dict()

    def _handle_evaluate_trade(self, payload: dict) -> dict:
        req = EvaluateTradePayload.model_validate(payload)
        user_roster = [self._to_projection(p) for p in req.user_roster]
        opponent_roster = [self._to_projection(p) for p in req.opponent_roster]
        result = evaluate_trade(
            self.state.config,
            user_roster,
            opponent_roster,
            current_week=req.current_week,
            user_gives=req.user_gives,
            user_receives=req.user_receives,
            opponent_expected_points=req.opponent_expected_points,
        )
        return result.to_dict()

    def _handle_faab_bids(self, payload: dict) -> dict:
        req = CalculateFaabBidsPayload.model_validate(payload)
        free_agents = (
            [self._to_projection(p) for p in req.free_agents]
            if req.free_agents
            else self.state.remaining()
        )
        all_players = (
            [self._to_projection(p) for p in req.all_players]
            if req.all_players
            else self.state.pool
        )
        bids = calculate_faab_bids(
            self.state.config,
            free_agents,
            all_players,
            current_week=req.current_week,
            user_budget=req.user_budget,
            roster_need=req.roster_need,
            rival_need_by_pos=req.rival_need_by_pos,
            rival_faab=req.rival_faab,
        )
        return {"bids": [b.to_dict() for b in bids]}

    def _to_projection(self, p: RosterPlayerPayload) -> PlayerProjection:
        """Resolve a wire roster player into a full :class:`PlayerProjection`."""
        pooled = self.state._by_id.get(p.player_id)
        fantasy_points = (
            p.fantasy_points
            if p.fantasy_points is not None
            else (pooled.fantasy_points if pooled else 0.0)
        )
        position: Position = p.position if pooled is None else pooled.position
        return PlayerProjection(
            player_id=p.player_id,
            name=p.name or (pooled.name if pooled else p.player_id),
            position=position,
            team=p.team or (pooled.team if pooled else ""),
            fantasy_points=fantasy_points,
        )

    def _to_optimizer_player(self, p: RosterPlayerPayload) -> OptimizerRosterPlayer:
        pooled = self.state._by_id.get(p.player_id)
        fantasy_points = (
            p.fantasy_points
            if p.fantasy_points is not None
            else (pooled.fantasy_points if pooled else 0.0)
        )
        position: Position = p.position if pooled is None else pooled.position
        return OptimizerRosterPlayer(
            player_id=p.player_id,
            name=p.name or (pooled.name if pooled else p.player_id),
            position=position,
            fantasy_points=fantasy_points,
            team=p.team or (pooled.team if pooled else ""),
            injury_tag=p.injury_tag,
            weather=p.weather,
            ceiling=p.ceiling,
            floor=p.floor,
        )

    _HANDLERS = {
        TYPE_SYNC: _handle_sync,
        TYPE_PICK: _handle_pick,
        TYPE_RECOMMEND: _handle_recommend,
        TYPE_RESET: _handle_reset,
        TYPE_OPTIMIZE: _handle_optimize_lineup,
        TYPE_EVALUATE_TRADE: _handle_evaluate_trade,
        TYPE_FAAB: _handle_faab_bids,
    }


async def handler(ws, session: DraftSession) -> None:
    """Per-connection handler loop.

    Sends the correlated ``RESPONSE`` back to the requesting client and fans
    any ``PICK_UPDATE`` broadcasts out to the other connected clients. This is
    how a pick streamed from the browser extension (one socket) instantly
    updates the desktop UI (a second socket).
    """
    session.clients.add(ws)
    try:
        async for message in ws:
            response, broadcasts = session.handle_frame(message)
            await ws.send(response)
            if broadcasts:
                await session.broadcast(broadcasts, exclude=ws)
    finally:
        session.clients.discard(ws)


async def run_server(host: str, port: int) -> None:
    session = DraftSession()
    stop = asyncio.get_running_loop().create_future()

    async def _signal() -> None:
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_signal()))
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    async with serve(
        lambda ws: handler(ws, session),
        host,
        port,
        max_size=10 * 1024 * 1024,
    ):
        logger.info("FDA WebSocket server listening on ws://%s:%d", host, port)
        await stop


async def _shutdown_for_test(server):
    """Awaitable helper used by tests to close a running server."""
    server.close()
    await server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description="FDA local WebSocket IPC server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(run_server(args.host, args.port))
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("server stopped")


if __name__ == "__main__":
    main()