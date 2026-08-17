/**
 * WebSocket bridge client for the Fantasy Draft Assistant.
 *
 * Talks to the local Python engine over `ws://127.0.0.1:8080`, correlating
 * request/response frames by `request_id`. The socket auto-reconnects on
 * drop (3s cadence) so the UI remains resilient during sidecar restarts.
 *
 * The wire format matches `src-python/protocol.py` and the TypeScript schema
 * in `src/types/protocol.ts`.
 */

import {
  BoardSnapshot,
  DraftPickMadePayload,
  Envelope,
  GetRecommendationsPayload,
  MessageType,
  PickAcceptedPayload,
  RecommendationsPayload,
  ResetDraftPayload,
  ResponsePayload,
  SyncLeagueConfigPayload,
} from "../types/protocol";

export const WS_URL = "ws://127.0.0.1:8080";
const RECONNECT_MS = 3000;
const REQUEST_TIMEOUT_MS = 5000;

type PendingResolver = {
  resolve: (value: ResponsePayload<unknown>) => void;
  reject: (reason: Error) => void;
};

let requestSeq = 0;

function nextRequestId(): string {
  requestSeq = (requestSeq + 1) % Number.MAX_SAFE_INTEGER;
  return `req-${requestSeq}`;
}

export class IpcError extends Error {
  code: string;

  constructor(message: string, code = "IPC_ERROR") {
    super(message);
    this.name = "IpcError";
    this.code = code;
  }
}

/**
 * Request/response transport for the engine bridge, with automatic
 * reconnection and per-request timeout guards.
 */
export class IpcClient {
  private ws: WebSocket | null = null;
  private pending = new Map<string, PendingResolver>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  connect(): void {
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    const ws = new WebSocket(WS_URL);
    this.ws = ws;

    ws.onmessage = (event: MessageEvent) => {
      let envelope: Envelope;
      try {
        envelope = JSON.parse(event.data as string);
      } catch {
        return;
      }
      if (envelope.type !== "RESPONSE") return;
      const resolver = this.pending.get(envelope.request_id ?? "");
      if (resolver) {
        this.pending.delete(envelope.request_id ?? "");
        resolver.resolve(envelope.payload as ResponsePayload<unknown>);
      }
    };

    ws.onclose = () => {
      this.ws = null;
      this.rejectPending(new IpcError("socket closed before response", "WS_CLOSED"));
      this.scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  /** Reject all in-flight requests so callers can retry or surface an error. */
  private rejectPending(reason: IpcError): void {
    for (const [id, resolver] of this.pending) {
      resolver.reject(reason);
      this.pending.delete(id);
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, RECONNECT_MS);
  }

  private request<T>(
    type: MessageType,
    payload: unknown,
  ): Promise<ResponsePayload<T>> {
    return new Promise<ResponsePayload<T>>((resolve, reject) => {
      this.connect();

      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new IpcError("websocket not connected", "WS_NOT_OPEN"));
        return;
      }

      const requestId = nextRequestId();
      this.pending.set(requestId, {
        resolve: (value) => resolve(value as ResponsePayload<T>),
        reject,
      });

      const envelope: Envelope = {
        type,
        request_id: requestId,
        payload,
      };
      this.ws.send(JSON.stringify(envelope));

      setTimeout(() => {
        if (this.pending.has(requestId)) {
          this.pending.delete(requestId);
          reject(new IpcError("request timed out", "TIMEOUT"));
        }
      }, REQUEST_TIMEOUT_MS);
    });
  }

  private async unwrap<T>(promise: Promise<ResponsePayload<T>>): Promise<T> {
    const response = await promise;
    if (response.ok) return response.data;
    throw new IpcError(response.error, response.code);
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  async syncLeagueConfig(payload: SyncLeagueConfigPayload): Promise<BoardSnapshot> {
    return this.unwrap(this.request<BoardSnapshot>("SYNC_LEAGUE_CONFIG", payload));
  }

  async getRecommendations(
    payload: GetRecommendationsPayload,
  ): Promise<RecommendationsPayload> {
    return this.unwrap(
      this.request<RecommendationsPayload>("GET_RECOMMENDATIONS", payload),
    );
  }

  async draftPickMade(
    payload: DraftPickMadePayload,
  ): Promise<PickAcceptedPayload> {
    return this.unwrap(
      this.request<PickAcceptedPayload>("DRAFT_PICK_MADE", payload),
    );
  }

  async resetDraft(payload: ResetDraftPayload = {}): Promise<BoardSnapshot> {
    return this.unwrap(this.request<BoardSnapshot>("RESET_DRAFT", payload));
  }
}