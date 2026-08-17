# Fantasy Draft Assistant — IPC Contract

Canonical wire contract for the local analytics-engine bridge. Mutable single
source of truth lives in `src-python/protocol.py`; the TypeScript
(`src/types/protocol.ts`) and Rust (`src-tauri/src/protocol.rs`) mirrors are
kept in lockstep with it.

## Transport

| Endpoint               | Protocol   | Purpose                          |
| ---------------------- | ---------- | -------------------------------- |
| `ws://127.0.0.1:8080`  | WebSocket  | Primary request/response channel |

## Message Types

| `type`               | Direction      | Description |
| -------------------- | -------------- | ----------- |
| `SYNC_LEAGUE_CONFIG` | client → server | Apply `LeagueConfig` and reset the live board |
| `DRAFT_PICK_MADE`    | client → server | Ingest a pick; return refreshed baselines |
| `GET_RECOMMENDATIONS`| client → server | Return top picks ranked by `U_i(t)` |
| `RESET_DRAFT`        | client → server | Clear the live draft board |
| `RESPONSE`           | server → client | Correlated reply envelope |

## Frame Envelope

```json
{ "type": "<TYPE>", "payload": { "...": "..." }, "request_id": "<id>" }
```

The server always echoes `request_id` on the matching `RESPONSE`. The response
`payload` is `{ "ok": true, "data": <data> }` on success and
`{ "ok": false, "error": "...", "code": "..." }` on failure.

## Key Naming Conventions

- Scoring fields use **snake_case** (e.g. `pass_yd`, `rec_td`, `te_rec_bonus`).
- Roster slots use **UPPERCASE** (e.g. `QB`, `FLEX`, `SUPERFLEX`).
- These match the pydantic field names in `engine/models.py`, which serialize
  verbatim to JSON.

## Payload Schemas

### `SYNC_LEAGUE_CONFIG`

`payload` is a `LeagueConfig` plus transport fields:

```json
{
  "name": "Full-PPR",
  "teams_count": 12,
  "scoring": {
    "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0,
    "rush_yd": 0.1,  "rush_td": 6.0, "rec": 1.0,
    "rec_yd": 0.1,  "rec_td": 6.0, "te_rec_bonus": 0.0,
    "fumble_lost": -2.0, "two_pt": 2.0
  },
  "roster_slots": {
    "QB": 1, "RB": 2, "WR": 2, "TE": 1,
    "FLEX": 1, "SUPERFLEX": 0, "BENCH": 6, "K": 0, "DST": 0
  },
  "user_team_index": 0,
  "allow_network": false
}
```

`data` (response): a `BoardSnapshot`.

### `GET_RECOMMENDATIONS`

```json
{ "user_team_index": 0, "r_next": 13, "limit": 8 }
```

All fields optional. `data` (response):

```json
{
  "user_team_index": 0,
  "r_next": 13,
  "available_count": 186,
  "recommendations": [
    {
      "player_id": "WR01", "name": "Wide Receiver 1",
      "position": "WR", "team": "TM01", "adp": 1, "bye_week": 6,
      "fantasy_points": 295.4, "dvorp": 92.1, "p_mb": 0.32,
      "r_need": 0.5, "p_bye": 0.0, "utility": 33.1
    }
  ]
}
```

### `DRAFT_PICK_MADE`

```json
{
  "pick_number": 1, "round": 1, "team_index": 1,
  "player_id": "WR01", "position": "WR", "fantasy_points": 295.4,
  "timestamp": 1720000000.0
}
```

`position` and `fantasy_points` are optional; the server derives them from its
pool. `data` (response):

```json
{
  "pick": {
    "pick_number": 1, "round": 1, "team_index": 1,
    "player_id": "WR01", "position": "WR", "fantasy_points": 295.4
  },
  "available_count": 185,
  "baselines": { "replacements": { "QB": 18.2, "RB": 12.8, "WR": 12.1, "TE": 8.9 } },
  "dvorp_updated": true
}
```

### `RESET_DRAFT`

```json
{ "keep_config": true }
```

`data` (response): a `BoardSnapshot`.

## `BoardSnapshot` (shared `data` shape)

```json
{
  "config": { "name": "...", "scoring": { "...": 0.0 }, "roster_slots": { "QB": 1 } },
  "user_team_index": 0,
  "drafted_count": 3,
  "available_count": 183,
  "picks": [],
  "user_owned": { "QB": 0, "RB": 0, "WR": 0, "TE": 0 }
}
```

## Latency Budget

`DRAFT_PICK_MADE` + `GET_RECOMMENDATIONS` (including full dynamic DVORP
recompute and decision-utility ranking) must complete in **< 50ms** per pick
event. Verified by `src-python/test_server.py`.