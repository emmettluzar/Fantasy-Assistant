"""Phase 2 acceptance test for the local WebSocket IPC bridge.

Verifies the four message types end-to-end and asserts the
``DRAFT_PICK_MADE`` + ``GET_RECOMMENDATIONS`` round trip (including a full
DVORP recompute) completes in under 50ms.

Run with the packaged virtual environment::

    src-python\\venv\\Scripts\\python src-python\\test_server.py
"""

from __future__ import annotations

import asyncio
import json
import time

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from server import DraftSession

# Non-default port so this test can run alongside a live sidecar server.
HOST = "127.0.0.1"
PORT = 8091
WS_URL = f"ws://{HOST}:{PORT}"

TARGET_MS = 50.0


def _frame(msg_type: str, payload: dict, request_id: str = "") -> str:
    return json.dumps({"type": msg_type, "payload": payload, "request_id": request_id})


async def request(ws, msg_type: str, payload: dict, request_id: str):
    """Send one frame and wait for the matching response envelope."""
    await ws.send(_frame(msg_type, payload, request_id))
    while True:
        response = json.loads(await ws.recv())
        if response.get("type") == "RESPONSE" and response.get("request_id") == request_id:
            return response


def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


async def run_test() -> int:
    failures: list[str] = []
    timings: list[float] = []

    # The same session the production server path uses, wired to a test port.
    session = DraftSession()

    async def ws_handler(ws):
        async for message in ws:
            await ws.send(session.handle(message))

    async with serve(ws_handler, HOST, PORT):
        async with connect(WS_URL) as ws:
            # ------------------------------------------------------------------
            # 1. SYNC_LEAGUE_CONFIG
            # ------------------------------------------------------------------
            response = await request(
                ws,
                "SYNC_LEAGUE_CONFIG",
                {
                    "name": "Test PPR",
                    "scoring": {"rec": 1.0, "pass_td": 4.0},
                    "roster_slots": {
                        "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1,
                    },
                    "teams_count": 12,
                    "user_team_index": 0,
                    "allow_network": False,
                },
                "sync-1",
            )
            body = response["payload"]
            if not body.get("ok"):
                failures.append(f"SYNC_LEAGUE_CONFIG failed: {body}")
            elif body["data"]["available_count"] <= 0:
                failures.append("SYNC_LEAGUE_CONFIG produced an empty pool")

            # ------------------------------------------------------------------
            # 2. GET_RECOMMENDATIONS (fresh board)
            # ------------------------------------------------------------------
            t0 = time.perf_counter()
            response = await request(ws, "GET_RECOMMENDATIONS", {"limit": 5}, "rec-1")
            rec_body = response["payload"]
            timings.append(elapsed_ms(t0))

            if not rec_body.get("ok"):
                failures.append(f"GET_RECOMMENDATIONS failed: {rec_body}")
            else:
                recs = rec_body["data"]["recommendations"]
                if len(recs) != 5:
                    failures.append(f"expected 5 recommendations, got {len(recs)}")
                for key in ("player_id", "name", "position", "dvorp", "utility"):
                    if key not in recs[0]:
                        failures.append(f"recommendation missing field: {key}")
                top_player_id = recs[0]["player_id"]

            # ------------------------------------------------------------------
            # 3. DRAFT_PICK_MADE + immediate recommendation refresh
            # ------------------------------------------------------------------
            t0 = time.perf_counter()
            response = await request(
                ws,
                "DRAFT_PICK_MADE",
                {
                    "pick_number": 1,
                    "round": 1,
                    "team_index": 1,
                    "player_id": top_player_id,
                },
                "pick-1",
            )
            pick_body = response["payload"]
            timings.append(elapsed_ms(t0))

            if not pick_body.get("ok"):
                failures.append(f"DRAFT_PICK_MADE failed: {pick_body}")
            else:
                data = pick_body["data"]
                if data["pick"]["player_id"] != top_player_id:
                    failures.append("pick echo mismatch")
                if set(data["baselines"]["replacements"]) != {"QB", "RB", "WR", "TE"}:
                    failures.append("pick response missing replacement baselines")

            # Refresh recommendations; drafted player must now be unavailable.
            t0 = time.perf_counter()
            response = await request(ws, "GET_RECOMMENDATIONS", {"limit": 5}, "rec-2")
            rec2 = response["payload"]
            timings.append(elapsed_ms(t0))

            if not rec2.get("ok"):
                failures.append(f"post-pick GET_RECOMMENDATIONS failed: {rec2}")
            else:
                ids = [r["player_id"] for r in rec2["data"]["recommendations"]]
                if top_player_id in ids:
                    failures.append("drafted player still present in recommendations")

            # ------------------------------------------------------------------
            # 4. RESET_DRAFT
            # ------------------------------------------------------------------
            response = await request(ws, "RESET_DRAFT", {"keep_config": True}, "reset-1")
            reset_body = response["payload"]
            if not reset_body.get("ok"):
                failures.append(f"RESET_DRAFT failed: {reset_body}")
            elif reset_body["data"]["drafted_count"] != 0:
                failures.append("RESET_DRAFT did not clear drafted players")

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("Phase 2: WebSocket IPC bridge acceptance test")
    print("=" * 78)

    if timings:
        avg = sum(timings) / len(timings)
        mx = max(timings)
        print(f"Round-trip latencies: {', '.join(f'{t:.2f}' for t in timings)} ms")
        print(f"Average: {avg:.2f}ms   Max: {mx:.2f}ms   Target: < {TARGET_MS}ms")
        if mx <= TARGET_MS:
            print("PERF: PASS  (max round trip under 50ms)")
        else:
            print("PERF: FAIL  (max round trip exceeded 50ms)")
            failures.append(f"max round trip {mx:.2f}ms exceeded 50ms")

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        print(f"\n{len(failures)} failure(s)")
        return 1

    print("\nALL CHECKS PASSED")
    return 0


def main() -> int:
    return asyncio.run(run_test())


if __name__ == "__main__":
    raise SystemExit(main())