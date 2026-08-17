/**
 * Zustand store bridging the React UI to the local analytics engine.
 *
 * Responsibilities:
 * - control the Python sidecar via Tauri commands (`start_engine`,
 *   `stop_engine`, `engine_status`).
 * - mirror live draft state using the WebSocket IPC client.
 * - expose typed actions for SYNC_LEAGUE_CONFIG, DRAFT_PICK_MADE,
 *   GET_RECOMMENDATIONS, and RESET_DRAFT.
 * - derive the normalized UI layer state (teams, draft grid picks, available
 *   player pool, player name index) consumed by the React components.
 */

import { create } from "zustand";
import { invoke } from "@tauri-apps/api/core";

import {
  IpcClient,
  IpcConnectionState,
  IpcError,
} from "../lib/ipcClient";
import {
  BoardSnapshot,
  DraftPickMadePayload,
  EngineStatus,
  GetRecommendationsPayload,
  LeagueConfig,
  DEFAULT_LEAGUE_CONFIG,
  PickUpdatePayload,
  PlatformRoster,
  Player,
  PlayerIndexEntry,
  Position,
  Recommendation,
  ResetDraftPayload,
  SnapshotPick,
  SyncLeagueConfigPayload,
  SyncPlatformLeaguePayload,
  Team,
} from "../types/protocol";

const ipc = new IpcClient();

/** Normalized draft pick consumed by the draft board grid. */
export interface DraftPickRow {
  pickNumber: number;
  round: number;
  teamIndex: number;
  playerId: string;
  playerName: string;
  position: Position;
  fantasyPoints: number;
}

/** Normalize a wire `Recommendation` into the UI `Player` record. */
function toPlayer(rec: Recommendation): Player {
  return {
    playerId: rec.player_id,
    name: rec.name,
    position: rec.position,
    team: rec.team,
    adp: rec.adp,
    byeWeek: rec.bye_week,
    fantasyPoints: rec.fantasy_points,
    xfp: rec.xfp ?? null,
    wopr: rec.wopr ?? null,
    dvorp: rec.dvorp,
    replacementValue: rec.fantasy_points - rec.dvorp,
    pMb: rec.p_mb,
    utility: rec.utility,
  };
}

/** Derive the ordered team list from the configured team count. */
function buildTeams(teamCount: number): Team[] {
  return Array.from({ length: teamCount }, (_, index) => ({
    index,
    name: `Team ${index + 1}`,
  }));
}

/** Derive the team list, prefering real platform roster names when present. */
function buildTeamsFromRosters(
  teamCount: number,
  rosters: PlatformRoster[] = [],
): Team[] {
  const byIndex = new Map<number, string>();
  for (const roster of rosters) {
    if (roster.team_name) byIndex.set(roster.team_index, roster.team_name);
  }
  return Array.from({ length: teamCount }, (_, index) => ({
    index,
    name: byIndex.get(index) ?? `Team ${index + 1}`,
  }));
}

interface DraftStore {
  // -------------------------------------------------------------------------
  // Engine lifecycle
  // -------------------------------------------------------------------------
  engine: EngineStatus | null;
  startEngine: () => Promise<void>;
  stopEngine: () => Promise<void>;
  refreshEngineStatus: () => Promise<void>;

  // -------------------------------------------------------------------------
  // WebSocket sync state
  // -------------------------------------------------------------------------
  connection: IpcConnectionState;
  subscribeConnection: () => () => void;
  subscribePicks: () => () => void;

  // -------------------------------------------------------------------------
  // League + draft board state
  // -------------------------------------------------------------------------
  config: LeagueConfig;
  teams: Team[];
  userTeamIndex: number;
  picks: DraftPickRow[];
  draftedCount: number;
  availableCount: number;
  rNext: number;
  platformRosters: PlatformRoster[];

  // -------------------------------------------------------------------------
  // Available player pool + recommendations
  // -------------------------------------------------------------------------
  playerPool: Player[];
  playerIndex: Record<string, PlayerIndexEntry>;
  recommendations: Recommendation[];
  loading: boolean;
  error: string | null;

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------
  syncLeagueConfig: (payload: SyncLeagueConfigPayload) => Promise<void>;
  syncPlatformLeague: (payload: SyncPlatformLeaguePayload) => Promise<void>;
  getRecommendations: (payload?: GetRecommendationsPayload) => Promise<void>;
  draftPickMade: (payload: DraftPickMadePayload) => Promise<void>;
  resetDraft: (payload?: ResetDraftPayload) => Promise<void>;
}

/** Helper to surface an error message while preserving the IPC error code when available. */
function errorMessage(err: unknown): string {
  if (err instanceof IpcError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

/**
 * Apply a `BoardSnapshot` from SYNC_LEAGUE_CONFIG / RESET_DRAFT into store
 * state without overwriting any existing player pool (which requires a
 * subsequent GET_RECOMMENDATIONS call to populate).
 */
function applySnapshot(
  snapshot: BoardSnapshot,
): Partial<DraftStore> {
  return {
    config: snapshot.config,
    teams: buildTeams(snapshot.config.teams_count),
    userTeamIndex: snapshot.user_team_index,
    draftedCount: snapshot.drafted_count,
    availableCount: snapshot.available_count,
    picks: snapshot.picks.map((p: SnapshotPick) => ({
      pickNumber: p.pick_number,
      round: p.round,
      teamIndex: p.team_index,
      playerId: p.player_id,
      playerName: p.player_id,
      position: p.position,
      fantasyPoints: p.fantasy_points,
    })),
  };
}

export const useDraftStore = create<DraftStore>((set, get) => {
  /**
   * Apply a server-pushed `PICK_UPDATE` to the live board.
   *
   * The pick originated on another socket (the browser extension or a Python
   * platform adapter). The payload carries a full `BoardSnapshot`, so we can
   * rebuild the authoritative pick grid locally and then refresh the remaining
   * player pool + next-pick value without a manual round-trip.
   */
  const hydratePickUpdate = (update: PickUpdatePayload) => {
    const { playerIndex } = get();
    const snapshot = update.snapshot;

    const picks: DraftPickRow[] = snapshot.picks.map((p: SnapshotPick) => ({
      pickNumber: p.pick_number,
      round: p.round,
      teamIndex: p.team_index,
      playerId: p.player_id,
      playerName: playerIndex[p.player_id]?.name ?? p.player_id,
      position: p.position,
      fantasyPoints: p.fantasy_points,
    }));

    set({
      config: snapshot.config,
      teams: buildTeams(snapshot.config.teams_count),
      userTeamIndex: snapshot.user_team_index,
      picks,
      draftedCount: snapshot.drafted_count,
      availableCount: snapshot.available_count,
    });

    // Refresh the remaining pool and next-pick value against the new board.
    void get().getRecommendations({});
  };

  return {
  engine: null,
  config: DEFAULT_LEAGUE_CONFIG,
  teams: [],
  userTeamIndex: 0,
  picks: [],
  draftedCount: 0,
  availableCount: 0,
  rNext: 0,
  platformRosters: [],

  playerPool: [],
  playerIndex: {},
  recommendations: [],
  loading: false,
  error: null,
  connection: ipc.getState(),

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
  // WebSocket sync state
  // -------------------------------------------------------------------------
  subscribeConnection: () => {
    const unsubscribe = ipc.onStateChange((connection) => {
      set({ connection });
    });
    // Immediately reconcile in case the state changed before subscription.
    set({ connection: ipc.getState() });
    return unsubscribe;
  },

  subscribePicks: () => {
    const unsubscribe = ipc.onPickUpdate((update: PickUpdatePayload) => {
      hydratePickUpdate(update);
    });
    return unsubscribe;
  },

  // -------------------------------------------------------------------------
  // Live draft state
  // -------------------------------------------------------------------------
  syncLeagueConfig: async (payload) => {
    set({ loading: true, error: null });
    try {
      const snapshot: BoardSnapshot = await ipc.syncLeagueConfig(payload);
      set({
        ...applySnapshot(snapshot),
        recommendations: [],
        playerPool: [],
        playerIndex: {},
        loading: false,
      });
      // Populate recommendations now that the board is configured.
      await get().getRecommendations();
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  syncPlatformLeague: async (payload) => {
    set({ loading: true, error: null });
    try {
      const result = await ipc.syncPlatformLeague(payload);
      set({
        config: result.config,
        teams: buildTeamsFromRosters(result.config.teams_count, result.rosters),
        userTeamIndex: result.user_team_index,
        platformRosters: result.rosters,
        picks: [],
        draftedCount: 0,
        availableCount: 0,
        rNext: 0,
        recommendations: [],
        playerPool: [],
        playerIndex: {},
        loading: false,
      });
      // Populate recommendations now that the league is configured.
      await get().getRecommendations();
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  getRecommendations: async (payload = {}) => {
    set({ loading: true, error: null });
    try {
      const result = await ipc.getRecommendations(payload);

      const pool: Player[] = [];
      const index: Record<string, PlayerIndexEntry> = {};
      for (const rec of result.recommendations) {
        pool.push(toPlayer(rec));
        index[rec.player_id] = {
          name: rec.name,
          position: rec.position,
          team: rec.team,
        };
      }

      set({
        recommendations: result.recommendations,
        playerPool: pool,
        playerIndex: index,
        availableCount: result.available_count,
        rNext: result.r_next,
        userTeamIndex: result.user_team_index,
        loading: false,
      });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  draftPickMade: async (payload) => {
    set({ error: null });
    try {
      // First renew the recommendations with the pick already ingested by the
      // server; this also returns fresh user_team_index / r_next.
      await ipc.draftPickMade(payload);

      const result = await ipc.getRecommendations({});

      const { playerIndex, picks } = get();
      const pool: Player[] = [];
      const index: Record<string, PlayerIndexEntry> = { ...playerIndex };
      for (const rec of result.recommendations) {
        pool.push(toPlayer(rec));
        index[rec.player_id] = {
          name: rec.name,
          position: rec.position,
          team: rec.team,
        };
      }

      const playerName = index[payload.player_id]?.name ?? payload.player_id;
      const nextPickNumber =
        picks.length > 0 ? Math.max(...picks.map((p) => p.pickNumber)) + 1 : 1;

      const newPick: DraftPickRow = {
        pickNumber: payload.pick_number ?? nextPickNumber,
        round: payload.round,
        teamIndex: payload.team_index,
        playerId: payload.player_id,
        playerName,
        position: index[payload.player_id]?.position ?? payload.position ?? "RB",
        fantasyPoints: payload.fantasy_points ?? 0,
      };

      set({
        recommendations: result.recommendations,
        playerPool: pool,
        playerIndex: index,
        availableCount: result.available_count,
        rNext: result.r_next,
        userTeamIndex: result.user_team_index,
        picks: [...picks, newPick],
        draftedCount: picks.length + 1,
      });
    } catch (err) {
      set({ error: errorMessage(err) });
    }
  },

  resetDraft: async (payload = {}) => {
    set({ loading: true, error: null });
    try {
      const snapshot: BoardSnapshot = await ipc.resetDraft(payload);
      set({
        ...applySnapshot(snapshot),
        recommendations: [],
        playerPool: [],
        playerIndex: {},
        rNext: 0,
        loading: false,
      });
      await get().getRecommendations();
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },
  };
});
