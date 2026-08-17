"""Phase 4 verification: extension broadcast + platform adapter normalizers.

Exercises (offline, no network):

1. Imports of the server, protocol, and all adapter modules.
2. The PlayerNormalizer collapsing Sleeper/ESPN/Yahoo identities.
3. The adapter normalize_pick methods on synthetic platform payloads.
4. The end-to-end live path: one WebSocket client sends a pick (as the browser
   extension does) and a *second* client (the desktop app) receives the
   ``PICK_UPDATE`` broadcast — proving picks streamed by the extension trigger
   live board updates on the desktop side.

Run with the venv interpreter from the repo root:

    src-python\\venv\\Scripts\\python src-python\\verify_phase4.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

sys.path.insert(0, "src-python")

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from server import DraftSession

HOST = "127.0.0.1"
PORT = 8092
WS_URL = f"ws://{HOST}:{PORT}"


def frame(msg_type: str, payload: dict, request_id: str = "") -> str:
    return json.dumps({"type": msg_type, "payload": payload, "request_id": request_id})


async def recv_response(ws, request_id: str):
    while True:
        message = json.loads(await ws.recv())
        if message.get("type") == "RESPONSE" and message.get("request_id") == request_id:
            return message


async def recv_pick_update(ws):
    while True:
        message = json.loads(await ws.recv())
        if message.get("type") == "PICK_UPDATE":
            return message


def check(name: str, condition: bool, failures: list[str], detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(name)


async def main() -> int:
    failures: list[str] = []

    print("=" * 78)
    print("Phase 4: extension broadcast + platform adapters verification")
    print("=" * 78)

    # ------------------------------------------------------------------
    # 1. Imports
    # ------------------------------------------------------------------
    print("\n[1] Module imports")
    try:
        import protocol  # noqa: F401
        import server  # noqa: F401
        import integrations  # noqa: F401
        from integrations import (  # noqa: F401
            EspnAdapter,
            PlayerNormalizer,
            SleeperAdapter,
            YahooAdapter,
        )
        check("import server/protocol/integrations", True, failures)
    except Exception as exc:
        check("import server/protocol/integrations", False, failures, str(exc))

    # ------------------------------------------------------------------
    # 2. PlayerNormalizer
    # ------------------------------------------------------------------
    print("\n[2] PlayerNormalizer cross-platform identity")
    normalizer = PlayerNormalizer()
    normalizer.register(
        player_id="RB01",
        name="Running Back 1",
        position="RB",
        platform="sleeper",
        platform_id="sleeper-9001",
    )
    normalizer.register(
        player_id="RB01",
        name="Running Back 1",
        platform="espn",
        platform_id="424242",
    )
    check("register + re-register keeps one canonical record", len(normalizer) == 1, failures)

    via_sleeper = normalizer.resolve(platform="sleeper", platform_id="sleeper-9001")
    via_espn = normalizer.resolve(platform="espn", platform_id="424242")
    via_name = normalizer.resolve(name="running back 1")
    check(
        "resolve by platform id + name",
        via_sleeper is not None
        and via_sleeper.player_id == "RB01"
        and via_espn is not None
        and via_espn.player_id == "RB01"
        and via_name is not None
        and via_name.player_id == "RB01",
        failures,
    )

    normalized = normalizer.normalize_pick(
        {"playerId": "424242", "team_index": 2, "pick_number": 7},
        platform="espn",
    )
    check(
        "engine-ready pick dict with canonical id",
        normalized is not None and normalized["player_id"] == "RB01" and normalized["pick_number"] == 7,
        failures,
        str(normalized),
    )

    # ------------------------------------------------------------------
    # 3. Adapter normalize_pick on synthetic payloads (no network)
    # ------------------------------------------------------------------
    print("\n[3] Adapter pick normalization")
    sleeper = SleeperAdapter("draft-123")
    sleeper.normalizer.register(
        player_id="WR01",
        name="Wide Receiver 1",
        position="WR",
        platform="sleeper",
        platform_id="wr-500",
    )
    sleeper_pick = sleeper.normalize_pick(
        {"player_id": "wr-500", "draft_slot": 3, "round": 1, "pick_no": 3}
    )
    check(
        "sleeper normalize_pick",
        sleeper_pick is not None
        and sleeper_pick["player_id"] == "WR01"
        and sleeper_pick["team_index"] == 2,
        failures,
        str(sleeper_pick),
    )

    espn = EspnAdapter(league_id=12345)
    espn_pick = espn.normalize_pick(
        {
            "player": {"playerId": "111", "fullName": "QB Star", "defaultPosition": "QB"},
            "teamId": 1,
            "roundNumber": 1,
            "overallPickNumber": 4,
        }
    )
    check(
        "espn normalize_pick",
        espn_pick is not None
        and espn_pick["player_id"] == "111"
        and espn_pick["position"] == "QB"
        and espn_pick["pick_number"] == 4,
        failures,
        str(espn_pick),
    )

    yahoo = YahooAdapter(league_id=56789)
    yahoo_pick = yahoo.normalize_pick(
        {
            "player_key": "nfl.p.222",
            "player": {"full_name": "TE Target", "display_position": "TE"},
            "team_index": 0,
            "round": 2,
            "pick": 5,
        }
    )
    check(
        "yahoo normalize_pick",
        yahoo_pick is not None
        and yahoo_pick["player_id"] == "nfl.p.222"
        and yahoo_pick["position"] == "TE"
        and yahoo_pick["pick_number"] == 5,
        failures,
        str(yahoo_pick),
    )

    # ------------------------------------------------------------------
    # 4. Live broadcast: extension socket -> server -> desktop socket
    # ------------------------------------------------------------------
    print("\n[4] Live broadcast (extension pick -> desktop PICK_UPDATE)")
    session = DraftSession()

    async def ws_handler(ws):
        session.clients.add(ws)
        try:
            async for message in ws:
                response, broadcasts = session.handle_frame(message)
                await ws.send(response)
                if broadcasts:
                    await session.broadcast(broadcasts, exclude=ws)
        finally:
            session.clients.discard(ws)

    async with serve(ws_handler, HOST, PORT):
        async with connect(WS_URL) as desktop_ws:
            # Desktop first syncs a league config over its own socket.
            await desktop_ws.send(
                frame(
                    "SYNC_LEAGUE_CONFIG",
                    {
                        "name": "Phase 4 Test",
                        "scoring": {"rec": 1.0},
                        "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
                        "teams_count": 12,
                        "user_team_index": 0,
                        "allow_network": False,
                    },
                    "sync-1",
                )
            )
            sync_response = await recv_response(desktop_ws, "sync-1")
            check(
                "desktop SYNC_LEAGUE_CONFIG ok",
                sync_response["payload"]["ok"] is True,
                failures,
            )

            # Fetch top recommendation to know a valid player_id to "pick".
            await desktop_ws.send(frame("GET_RECOMMENDATIONS", {"limit": 1}, "rec-1"))
            rec_response = await recv_response(desktop_ws, "rec-1")
            top_id = rec_response["payload"]["data"]["recommendations"][0]["player_id"]
            check("desktop GET_RECOMMENDATIONS ok", rec_response["payload"]["ok"] is True, failures)

            # The "extension" connects on a separate socket and sends a pick.
            async with connect(WS_URL) as extension_ws:
                await extension_ws.send(
                    frame(
                        "DRAFT_PICK_MADE",
                        {"pick_number": 1, "round": 1, "team_index": 1, "player_id": top_id},
                        "ext-1",
                    )
                )
                ext_response = await recv_response(extension_ws, "ext-1")
                check(
                    "extension DRAFT_PICK_MADE accepted",
                    ext_response["payload"]["ok"] is True,
                    failures,
                )

                # The desktop socket should receive the PICK_UPDATE broadcast.
                update = await asyncio.wait_for(recv_pick_update(desktop_ws), timeout=3.0)
                check(
                    "desktop receives PICK_UPDATE broadcast",
                    update["payload"]["pick"]["player_id"] == top_id
                    and update["payload"]["snapshot"]["drafted_count"] == 1,
                    failures,
                    f"picked={update['payload']['pick']['player_id']}",
                )

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    if failures:
        print(f"RESULT: FAIL ({len(failures)} failure(s))")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))