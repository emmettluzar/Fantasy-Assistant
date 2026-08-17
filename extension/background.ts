/// <reference path="./shared.d.ts" />

/**
 * Manifest v3 service worker.
 *
 * Owns the single WebSocket connection to `ws://127.0.0.1:8080` (the local
 * desktop engine). Content-script and page-interceptor events are normalized
 * into `DRAFT_PICK_MADE` envelopes and streamed here.
 *
 * Connection lifecycle:
 *   - connect on startup / message / alarm
 *   - auto-reconnect with backoff
 *   - a keep-alive alarm ensures the MV3 worker survives while a draft is open.
 */

const WS_URL = "ws://127.0.0.1:8080";
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;
// Alarms API minimum is 0.5 minutes (30s). The open WebSocket already keeps
// the MV3 worker alive; this alarm is a reconnect fallback if the socket drops.
const KEEPALIVE_PERIOD_MIN = 0.5;

let ws: WebSocket | null = null;
let backoff = RECONNECT_BASE_MS;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let keepAliveTimer: ReturnType<typeof setInterval> | null = null;
let requestSeq = 0;

// ---------------------------------------------------------------------------
// Deduplication across content-script / interceptor reports.
// ---------------------------------------------------------------------------
const seen = new Set<string>();
function remember(key: string): boolean {
  if (seen.has(key)) return false;
  seen.add(key);
  if (seen.size > 5000) {
    const oldest = seen.values().next().value;
    if (oldest !== undefined) seen.delete(oldest);
  }
  return true;
}

function fingerprint(payload: Record<string, unknown>): string {
  return `${payload.platform ?? "unknown"}:${payload.player_id}:${payload.team_index}:${payload.pick_number}`;
}

// ---------------------------------------------------------------------------
// Normalization helpers borrowed from the engine's protocol schema.
// ---------------------------------------------------------------------------
function toInt(v: unknown): number | undefined {
  if (typeof v === "number") return Number.isFinite(v) ? Math.trunc(v) : undefined;
  if (typeof v === "string") {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : undefined;
  }
  return undefined;
}

function normalizePosition(v: unknown): TransportPosition | undefined {
  if (typeof v !== "string") return undefined;
  const s = v.trim().toUpperCase();
  if (s === "K") return "K";
  if (s === "DST" || s === "DEF" || s === "D/ST" || s === "D") return "DST";
  if (s === "QB" || s === "RB" || s === "WR" || s === "TE") return s;
  return undefined;
}

function asRecord(event: unknown): Record<string, unknown> {
  return event && typeof event === "object"
    ? (event as Record<string, unknown>)
    : {};
}

/**
 * Coerce an arbitrary payload into the canonical `DRAFT_PICK_MADE` schema.
 * Returns `null` if the payload cannot be turned into a valid, unique pick.
 */
function normalizePickPayload(event: unknown): PickMessagePayload | null {
  const payload = asRecord(event);
  const platform = payload.platform as "espn" | "yahoo" | "sleeper" | undefined;

  const playerId = String(
    payload.player_id ?? payload.playerId ?? payload.playerID ?? payload.id ?? "",
  ).trim();
  const playerName = String(
    payload.player_name ?? payload.playerName ?? payload.name ?? "",
  ).trim();

  const position = normalizePosition(payload.position ?? payload.pos ?? payload.slot);

  const teamIndex = toInt(
    payload.team_index ?? payload.teamIndex ?? payload.draft_slot ?? payload.draftSlot,
  );
  const round = toInt(payload.round ?? payload.rnd ?? payload.round_number) || 1;
  const pickNumber = toInt(
    payload.pick_number ?? payload.pickNumber ?? payload.overall_pick ?? payload.overallPick,
  );

  const rawTs = payload.timestamp ?? payload.picked_at ?? payload.ts;
  const timestamp =
    typeof rawTs === "number" && Number.isFinite(rawTs) ? rawTs : undefined;

  if (!playerId || teamIndex === undefined || !pickNumber) {
    return null;
  }

  const normalized: PickMessagePayload = {
    pick_number: pickNumber,
    round,
    team_index: teamIndex,
    player_id: playerId,
    position,
    fantasy_points:
      typeof payload.fantasy_points === "number" ? payload.fantasy_points : undefined,
    timestamp,
  };
  if (platform) normalized.platform = platform;
  if (playerName) normalized.player_name = playerName;

  if (!remember(fingerprint(normalized as unknown as Record<string, unknown>))) {
    return null;
  }
  return normalized;
}

// ---------------------------------------------------------------------------
// Engine Socket
// ---------------------------------------------------------------------------
function scheduleReconnect(): void {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, backoff);
  backoff = Math.min(backoff * 2, RECONNECT_MAX_MS);
}

function ensureKeepAlive(): void {
  if (keepAliveTimer) return;
  keepAliveTimer = setInterval(() => {
    // A no-op alarm keeps the MV3 service worker alive while a draft is open.
  }, KEEPALIVE_PERIOD_MIN * 60 * 1000);
}

function connect(): void {
  if (
    ws &&
    (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }

  try {
    ws = new WebSocket(WS_URL);
  } catch (_) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    backoff = RECONNECT_BASE_MS;
    ensureKeepAlive();
  };

  ws.onclose = () => {
    ws = null;
    scheduleReconnect();
  };

  ws.onerror = () => {
    try {
      if (ws) ws.close();
    } catch (_) {
      /* no-op */
    }
  };

  ws.onmessage = () => {
    // Responses from the engine are informational for the extension; a
    // successful `DRAFT_PICK_MADE` implies the engine already ingested it.
  };
}

function send(payload: PickMessagePayload): void {
  try {
    connect();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      scheduleReconnect();
      return;
    }
    requestSeq = (requestSeq + 1) % Number.MAX_SAFE_INTEGER;
    const envelope: PickEnvelope = {
      type: "DRAFT_PICK_MADE",
      request_id: `ext-${requestSeq}`,
      payload,
    };
    ws.send(JSON.stringify(envelope));
  } catch (_) {
    scheduleReconnect();
  }
}

// ---------------------------------------------------------------------------
// Message routing
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  try {
    if (!message || typeof message !== "object") return false;

    if (message.kind === "raw-event") {
      const event = message.event as { kind?: string; payload?: unknown } | undefined;
      if (event && event.kind === "pick") {
        const payload = normalizePickPayload(event.payload);
        if (payload) send(payload);
      }
      sendResponse({ ok: true });
      return false;
    }

    if (message.kind === "mock-pick") {
      const payload = normalizePickPayload(message.payload);
      if (payload) send(payload);
      sendResponse({ ok: Boolean(payload) });
      return false;
    }
  } catch (_) {
    /* best-effort */
  }
  return false;
});

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
function syncAlarm(): void {
  chrome.alarms.create("fda-ws-keepalive", {
    delayInMinutes: KEEPALIVE_PERIOD_MIN,
    periodInMinutes: KEEPALIVE_PERIOD_MIN,
  });
}

chrome.runtime.onInstalled.addListener(() => {
  syncAlarm();
  connect();
});

chrome.runtime.onStartup.addListener(() => {
  syncAlarm();
  connect();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "fda-ws-keepalive") {
    connect();
  }
});

// Connect as soon as the worker spins up (e.g. from a content-script wake).
syncAlarm();
connect();