"""Local WebSocket IPC server for the Fantasy Draft Assistant.

Listens on ``ws://127.0.0.1:8080`` (see ``IPC_PROTOCOL.md``) and handles the
four message types:

* ``SYNC_LEAGUE_CONFIG`` -- applies a new :class:`LeagueConfig`.
* ``DRAFT_PICK_MADE``   -- ingests a pick, then returns refreshed baselines.
* ``GET_RECOMMENDATIONS`` -- returns the top available players by ``U_i(t)``.
* ``RESET_DRAFT``       -- clears the live draft board.

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

from protocol import (
    DraftPickMadePayload,
    GetRecommendationsPayload,
    ResetDraftPayload,
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

    def handle(self, message: str) -> str:
        """Dispatch one inbound frame and return the outbound JSON text."""
        try:
            frame = json.loads(message)
        except json.JSONDecodeError as exc:
            return _response(None, _error(f"invalid JSON: {exc}"))

        if not isinstance(frame, dict):
            return _response(None, _error("frame must be a JSON object"))

        msg_type = frame.get("type")
        if not isinstance(msg_type, str):
            return _response(None, _error("missing or invalid 'type'"))

        payload = frame.get("payload", {})
        if not isinstance(payload, dict):
            return _response(None, _error("'payload' must be a JSON object"))

        request_id = frame.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            return _response(None, _error("'request_id' must be a string"))

        handler = self._HANDLERS.get(msg_type)
        if handler is None:
            return _response(request_id, _error(f"unknown message type: {msg_type}"))

        try:
            data = handler(self, payload)
            return _response(request_id, {"ok": True, "data": data})
        except ValueError as exc:
            return _response(request_id, _error(str(exc)))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("unhandled error handling %s", msg_type)
            return _response(request_id, _error(str(exc), code="INTERNAL_ERROR"))

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

    _HANDLERS = {
        TYPE_SYNC: _handle_sync,
        TYPE_PICK: _handle_pick,
        TYPE_RECOMMEND: _handle_recommend,
        TYPE_RESET: _handle_reset,
    }


async def handler(ws, session: DraftSession) -> None:
    """Per-connection handler loop."""
    async for message in ws:
        response = session.handle(message)
        await ws.send(response)


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