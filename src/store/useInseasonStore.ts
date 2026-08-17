/**
 * Zustand store bridging the in-season automation UI to the local engine.
 *
 * Wraps the three Phase 5 IPC methods — OPTIMIZE_LINEUP, EVALUATE_TRADE, and
 * CALCULATE_FAAB_BIDS — and holds their most recent results for the
 * LineupOptimizerView, WaiverAssistantView, and TradeAnalyzerView components.
 *
 * The live WebSocket transport is shared from `lib/ipcClient`; this store only
 * adds typed actions and UI-level loading/error state.
 */

import { create } from "zustand";

import { IpcClient } from "../lib/ipcClient";
import {
  CalculateFaabBidsPayload,
  EvaluateTradePayload,
  FaabBidsPayload,
  LineupOptimizationPayload,
  OptimizeLineupPayload,
  TradeEvaluationPayload,
} from "../types/protocol";

const ipc = new IpcClient();

interface InseasonStore {
  // -------------------------------------------------------------------------
  // Lineup optimizer
  // -------------------------------------------------------------------------
  lineup: LineupOptimizationPayload | null;
  optimizeLineup: (payload: OptimizeLineupPayload) => Promise<void>;

  // -------------------------------------------------------------------------
  // Trade analyzer
  // -------------------------------------------------------------------------
  trade: TradeEvaluationPayload | null;
  evaluateTrade: (payload: EvaluateTradePayload) => Promise<void>;

  // -------------------------------------------------------------------------
  // Waiver assistant
  // -------------------------------------------------------------------------
  faabBids: FaabBidsPayload | null;
  calculateFaabBids: (payload: CalculateFaabBidsPayload) => Promise<void>;

  // -------------------------------------------------------------------------
  // Shared
  // -------------------------------------------------------------------------
  loading: boolean;
  error: string | null;
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

export const useInseasonStore = create<InseasonStore>((set) => ({
  lineup: null,
  trade: null,
  faabBids: null,
  loading: false,
  error: null,

  optimizeLineup: async (payload) => {
    set({ loading: true, error: null });
    try {
      const lineup = await ipc.optimizeLineup(payload);
      set({ lineup, loading: false });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  evaluateTrade: async (payload) => {
    set({ loading: true, error: null });
    try {
      const trade = await ipc.evaluateTrade(payload);
      set({ trade, loading: false });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  calculateFaabBids: async (payload) => {
    set({ loading: true, error: null });
    try {
      const faabBids = await ipc.calculateFaabBids(payload);
      set({ faabBids, loading: false });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },
}));