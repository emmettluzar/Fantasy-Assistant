/**
 * Zustand store bridging the React UI to the local analytics engine.
 *
 * Responsibilities:
 * - control the Python sidecar via Tauri commands (`start_engine`,
 *   `stop_engine`, `engine_status`).
 * - mirror live draft state using the WebSocket IPC client.
 * - expose typed actions for SYNC_LEAGUE_CONFIG, DRAFT_PICK_MADE,
 *   GET_RECOMMENDATIONS, and RESET_DRAFT.
 */

import { create } from "zustand";
import { invoke } from "@tauri-apps/api/core";

import { IpcClient } from "../lib/ipcClient";
import {
  BoardSnapshot,
  DraftPickMadePayload,
  EngineStatus,
  GetRecommendationsPayload,
  LeagueConfig,
  Recommendation,
  ResetDraftPayload,
  SyncLeagueConfigPayload,
} from "../types/protocol";

const ipc = new IpcClient();

interface DraftStore {
  // Engine lifecycle
  engine: EngineStatus | null;
  startEngine: () => Promise<void>;
  stopEngine: () => Promise<void>;
  refreshEngineStatus: () => Promise<void>;

  // Live draft state
  config: LeagueConfig | null;
  recommendations: Recommendation[];
  availableCount: number;
  loading: boolean;
  error: string | null;

  syncLeagueConfig: (payload: SyncLeagueConfigPayload) => Promise<void>;
  getRecommendations: (payload?: GetRecommendationsPayload) => Promise<void>;
  draftPickMade: (payload: DraftPickMadePayload) => Promise<void>;
  resetDraft: (payload?: ResetDraftPayload) => Promise<void>;
}

export const useDraftStore = create<DraftStore>((set) => ({
  engine: null,
  config: null,
  recommendations: [],
  availableCount: 0,
  loading: false,
  error: null,

  // -------------------------------------------------------------------------
  // Engine lifecycle
  // -------------------------------------------------------------------------
  startEngine: async () => {
    const status = await invoke<EngineStatus>("start_engine");
    set({ engine: status });
  },

  stopEngine: async () => {
    const status = await invoke<EngineStatus>("stop_engine");
    set({ engine: status });
  },

  refreshEngineStatus: async () => {
    const status = await invoke<EngineStatus>("engine_status");
    set({ engine: status });
  },

  // -------------------------------------------------------------------------
  // Live draft state
  // -------------------------------------------------------------------------
  syncLeagueConfig: async (payload) => {
    set({ loading: true, error: null });
    try {
      const snapshot: BoardSnapshot = await ipc.syncLeagueConfig(payload);
      set({
        config: snapshot.config,
        availableCount: snapshot.available_count,
        loading: false,
      });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  getRecommendations: async (payload = {}) => {
    set({ loading: true, error: null });
    try {
      const result = await ipc.getRecommendations(payload);
      set({
        recommendations: result.recommendations,
        availableCount: result.available_count,
        loading: false,
      });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  draftPickMade: async (payload) => {
    set({ error: null });
    try {
      const result = await ipc.draftPickMade(payload);
      set({ availableCount: result.available_count });
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  resetDraft: async (payload = {}) => {
    set({ loading: true, error: null });
    try {
      const snapshot: BoardSnapshot = await ipc.resetDraft(payload);
      set({
        config: snapshot.config,
        recommendations: [],
        availableCount: snapshot.available_count,
        loading: false,
      });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },
}));