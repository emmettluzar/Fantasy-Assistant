/**
 * Wire types shared by the Manifest v3 service worker, content script, and
 * page-injected interceptor. These mirror the canonical `src-python/protocol.py`
 * schema but intentionally carry only the subset the extension needs:
 * `DRAFT_PICK_MADE` frames it forwards to `ws://127.0.0.1:8080`.
 *
 * This file declares globals (no imports/exports) so the other extension
 * scripts can reference these types via a triple-slash reference without
 * becoming ES modules themselves. The extension ships as plain JavaScript
 * compiled from its TypeScript sources.
 */

type TransportPosition = "QB" | "RB" | "WR" | "TE" | "K" | "DST";

/** Normalized pick event forwarded over the bridge. */
interface PickMessagePayload {
  pick_number: number;
  round: number;
  team_index: number;
  player_id: string;
  position?: TransportPosition;
  fantasy_points?: number;
  /** Platform-native ID carried through for the normalizer; ignored by engine. */
  platform?: "espn" | "yahoo" | "sleeper";
  /** Bare player display name, used by the normalizer / debuggability. */
  player_name?: string;
  timestamp?: number;
}

interface PickEnvelope {
  type: "DRAFT_PICK_MADE";
  payload: PickMessagePayload;
  request_id?: string;
}

/** A raw event announced by the page interceptor to the content script. */
interface RawDraftEvent {
  platform: "espn" | "yahoo" | "sleeper";
  kind:
    | "pick"
    | "network"
    | "dom-candidate"
    | "draft-started"
    | "draft-completed";
  payload?: unknown;
  ts: number;
}

/** Bridge status message announced by the injected interceptor. */
interface BridgeStatus {
  source: "fantasy-draft-assistant-bridge";
  state: "connected" | "disconnected" | "error";
  detail?: string;
}

/** Shape of the global bridge object installed on `window`. */
interface Bridge {
  post: (event: RawDraftEvent) => void;
  ready: Promise<BridgeStatus>;
}

/** A pick-like row extracted from a platform payload before normalization. */
interface PickCandidate {
  playerName?: unknown;
  playerId?: unknown;
  position?: unknown;
  teamIndex?: unknown;
  round?: unknown;
  pickNumber?: unknown;
  timestamp?: unknown;
}

interface Window {
  __FDA_BRIDGE__?: Bridge;
  __FDA_BRIDGE_INSTALLED__?: boolean;
  /** Optional draft state exposed by some Sleeper SPA builds. */
  __SLEEPER_DRAFT_STATE__?: any;
}

/**
 * Minimal ambient surface for the Chrome extension APIs used by the extension.
 * The project does not depend on `@types/chrome`, so we declare only the
 * members actually exercised (`runtime`, `alarms`).
 */
declare const chrome: {
  runtime: {
    getURL: (path: string) => string;
    sendMessage: (message: unknown) => Promise<unknown>;
    onMessage: {
      addListener: (
        callback: (
          message: any,
          sender: any,
          sendResponse: (response?: unknown) => void,
        ) => boolean | void,
      ) => void;
    };
    onInstalled: { addListener: (callback: () => void) => void };
    onStartup: { addListener: (callback: () => void) => void };
  };
  alarms: {
    create: (name: string, alarmInfo: Record<string, unknown>) => void;
    onAlarm: { addListener: (callback: (alarm: { name?: string }) => void) => void };
  };
};