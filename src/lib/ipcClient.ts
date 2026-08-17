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
  CalculateFaabBidsPayload,
  DraftPickMadePayload,
  Envelope,
  EvaluateTradePayload,
  FaabBidsPayload,
  GetRecommendationsPayload,
  LineupOptimizationPayload,
  MessageType,
  OptimizeLineupPayload,
  PickAcceptedPayload,
  PickUpdatePayload,
  RecommendationsPayload,
  ResetDraftPayload,
  ResponsePayload,
  SyncLeagueConfigPayload,
  TradeEvaluationPayload,
} from "../types/protocol";

export const WS_URL = "ws://127.0.0.1:8080";
const RECONNECT_MS = 3000;
const REQUEST_TIMEOUT_MS = 5000;

/** High-level WebSocket lifecycle state exposed to the UI status badge. */
export type IpcConnectionState = "connecting" | "connected" | "disconnected";

/** Callback invoked whenever the WebSocket connection state changes. */
export type IpcStateListener = (state: IpcConnectionState) => void;

/** Callback invoked when the server pushes a live ``PICK_UPDATE`` frame. */
export type PickUpdateListener = (update: PickUpdatePayload) => void;

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
  private state: IpcConnectionState = "disconnected";
  private listeners = new Set<IpcStateListener>();
  private pickListeners = new Set<PickUpdateListener>();

  /** Current high-level connection state. */
  getState(): IpcConnectionState {
    return this.state;
  }

  /** Subscribe to connection-state changes. Returns an unsubscribe function. */
  onStateChange(listener: IpcStateListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Subscribe to live ``PICK_UPDATE`` pushes. Returns an unsubscribe function. */
  onPickUpdate(listener: PickUpdateListener): () => void {
    this.pickListeners.add(listener);
    return () => {
      this.pickListeners.delete(listener);
    };
  }

  private setState(next: IpcConnectionState): void {
    if (this.state === next) return;
    this.state = next;
    for (const listener of this.listeners) {
      listener(next);
    }
  }

  connect(): void {
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    this.setState("connecting");
    const ws = new WebSocket(WS_URL);
    this.ws = ws;

    ws.onopen = () => {
      this.setState("connected");
    };

    ws.onmessage = (event: MessageEvent) => {
      let envelope: Envelope;
      try {
        envelope = JSON.parse(event.data as string);
      } catch {
        return;
      }

      // Server-push used when a platform adapter or the browser extension
      // ingests a pick on a *different* socket: fan it out to UI subscribers.
      if (envelope.type === "PICK_UPDATE") {
        const payload = envelope.payload as PickUpdatePayload;
        for (const listener of this.pickListeners) {
          listener(payload);
        }
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
      this.setState("disconnected");
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

  async optimizeLineup(
    payload: OptimizeLineupPayload,
  ): Promise<LineupOptimizationPayload> {
    return this.unwrap(
      this.request<LineupOptimizationPayload>("OPTIMIZE_LINEUP", payload),
    );
  }

  async evaluateTrade(
    payload: EvaluateTradePayload,
  ): Promise<TradeEvaluationPayload> {
    return this.unwrap(
      this.request<TradeEvaluationPayload>("EVALUATE_TRADE", payload),
    );
  }

  async calculateFaabBids(
    payload: CalculateFaabBidsPayload,
  ): Promise<FaabBidsPayload> {
    return this.unwrap(
      this.request<FaabBidsPayload>("CALCULATE_FAAB_BIDS", payload),
    );
  }
}
