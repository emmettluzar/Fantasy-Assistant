/**
 * IPC message schema for the Fantasy Draft Assistant bridge.
 *
 * This file is the TypeScript mirror of:
 *
 * - src-python/protocol.py  (Python / pydantic)
 * - src-tauri/src/protocol.rs (Rust / serde)
 *
 * The canonical wire format originates from the pydantic models in
 * `engine/models.py`, so scoring fields use snake_case keys and roster slots
 * use UPPERCASE keys. Frames on the wire use the envelope:
 *
 *   { "type": "<TYPE>", "payload": { ... }, "request_id": "<id>" }
 */

export type MessageType =
  | "SYNC_LEAGUE_CONFIG"
  | "SYNC_PLATFORM_LEAGUE"
  | "DRAFT_PICK_MADE"
  | "GET_RECOMMENDATIONS"
  | "RESET_DRAFT"
  | "OPTIMIZE_LINEUP"
  | "EVALUATE_TRADE"
  | "CALCULATE_FAAB_BIDS"
  | "RESPONSE"
  | "PICK_UPDATE";

export type Position = "QB" | "RB" | "WR" | "TE" | "K" | "DST";

export const DEFAULT_WS_URL = "ws://127.0.0.1:8080";
export const DEFAULT_LIMIT = 8;
export const MAX_LIMIT = 50;

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

export interface Envelope<T = unknown> {
  type: MessageType;
  request_id?: string;
  payload: T;
}

// ---------------------------------------------------------------------------
// Scoring rules (snake_case keys)
// ---------------------------------------------------------------------------

export interface ScoringRules {
  pass_yd: number;
  pass_td: number;
  pass_int: number;
  rush_yd: number;
  rush_td: number;
  rec: number;
  rec_yd: number;
  rec_td: number;
  te_rec_bonus: number;
  fumble_lost: number;
  two_pt: number;
}

export const DEFAULT_SCORING: ScoringRules = {
  pass_yd: 0.04,
  pass_td: 4.0,
  pass_int: -2.0,
  rush_yd: 0.1,
  rush_td: 6.0,
  rec: 0.0,
  rec_yd: 0.1,
  rec_td: 6.0,
  te_rec_bonus: 0.0,
  fumble_lost: -2.0,
  two_pt: 2.0,
};

// ---------------------------------------------------------------------------
// Roster settings (UPPERCASE keys)
// ---------------------------------------------------------------------------

export interface RosterSettings {
  QB: number;
  RB: number;
  WR: number;
  TE: number;
  FLEX: number;
  SUPERFLEX: number;
  BENCH: number;
  K: number;
  DST: number;
}

export const DEFAULT_ROSTER: RosterSettings = {
  QB: 1,
  RB: 2,
  WR: 2,
  TE: 1,
  FLEX: 1,
  SUPERFLEX: 0,
  BENCH: 6,
  K: 0,
  DST: 0,
};

// ---------------------------------------------------------------------------
// League configuration
// ---------------------------------------------------------------------------

export interface LeagueConfig {
  name: string;
  scoring: ScoringRules;
  roster_slots: RosterSettings;
  teams_count: number;
}

export const DEFAULT_LEAGUE_CONFIG: LeagueConfig = {
  name: "Custom",
  scoring: DEFAULT_SCORING,
  roster_slots: DEFAULT_ROSTER,
  teams_count: 12,
};

// ---------------------------------------------------------------------------
// Message payloads
// ---------------------------------------------------------------------------

export interface SyncLeagueConfigPayload extends LeagueConfig {
  user_team_index?: number;
  allow_network?: boolean;
}

export interface GetRecommendationsPayload {
  user_team_index?: number;
  r_next?: number;
  limit?: number;
}

export interface DraftPickMadePayload {
  pick_number: number;
  round: number;
  team_index: number;
  player_id: string;
  position?: Position;
  fantasy_points?: number;
  timestamp?: number;
}

export interface ResetDraftPayload {
  keep_config?: boolean;
}

// ---------------------------------------------------------------------------
// Platform league connection (Phase: Connect League)
// ---------------------------------------------------------------------------

export type PlatformName = "sleeper" | "espn" | "yahoo";

export interface SyncPlatformLeaguePayload {
  platform: PlatformName;
  league_id?: string;
  // Sleeper
  draft_id?: string;
  username?: string;
  user_team_index?: number;
  // ESPN
  year?: number;
  espn_s2?: string;
  swid?: string;
  // Yahoo
  oauth_key?: string;
  allow_network?: boolean;
}

export interface PlatformRosterPlayer {
  player_id: string;
  name?: string | null;
  position?: string | null;
}

export interface PlatformRoster {
  team_index: number;
  team_name: string;
  players: PlatformRosterPlayer[];
}

export interface SyncPlatformLeagueResponse {
  config: LeagueConfig;
  user_team_index: number;
  rosters: PlatformRoster[];
}

// ---------------------------------------------------------------------------
// In-season automation payloads (Phase 5)
// ---------------------------------------------------------------------------

export interface RosterPlayerPayload {
  player_id: string;
  name?: string;
  position: Position;
  fantasy_points?: number;
  team?: string;
  injury_tag?: string | null;
  weather?: string | null;
  ceiling?: number;
  floor?: number;
}

export interface OptimizeLineupPayload {
  roster: RosterPlayerPayload[];
}

export interface EvaluateTradePayload {
  user_roster: RosterPlayerPayload[];
  opponent_roster: RosterPlayerPayload[];
  user_gives: string[];
  user_receives: string[];
  current_week?: number;
  opponent_expected_points?: number;
}

export interface CalculateFaabBidsPayload {
  free_agents: RosterPlayerPayload[];
  all_players: RosterPlayerPayload[];
  current_week?: number;
  user_budget?: number;
  roster_need?: Record<Position, number>;
  rival_need_by_pos?: Record<Position, number>;
  rival_faab?: number[];
}

// ---------------------------------------------------------------------------
// Response payloads
// ---------------------------------------------------------------------------

export interface Recommendation {
  player_id: string;
  name: string;
  position: Position;
  team: string;
  adp: number | null;
  bye_week: number;
  fantasy_points: number;
  /** Expected fantasy points (opportunity-based). Optional until the engine
   *  emits it on the recommendation payload. */
  xfp?: number | null;
  /** Weighted Opportunity Rating. Optional until the engine emits it. */
  wopr?: number | null;
  dvorp: number;
  p_mb: number;
  r_need: number;
  p_bye: number;
  utility: number;
}

export interface RecommendationsPayload {
  user_team_index: number;
  r_next: number;
  available_count: number;
  recommendations: Recommendation[];
}

export interface PickEcho {
  pick_number: number;
  round: number;
  team_index: number;
  player_id: string;
  position: Position;
  fantasy_points: number;
}

export interface PickAcceptedPayload {
  pick: PickEcho;
  available_count: number;
  baselines: { replacements: Record<Position, number> };
  dvorp_updated: boolean;
}

export interface SnapshotPick {
  pick_number: number;
  round: number;
  team_index: number;
  player_id: string;
  position: Position;
  fantasy_points: number;
  timestamp?: number | null;
}

export interface BoardSnapshot {
  config: LeagueConfig;
  user_team_index: number;
  drafted_count: number;
  available_count: number;
  picks: SnapshotPick[];
  user_owned: Record<Position, number>;
}

/**
 * Server-push payload broadcast to every other connected client after a pick
 * is ingested. The extension streams picks over one socket; the desktop board
 * receives this over its own socket and applies the change instantly.
 */
export interface PickUpdatePayload {
  pick: PickEcho;
  available_count: number;
  baselines: { replacements: Record<Position, number> };
  dvorp_updated: boolean;
  snapshot: BoardSnapshot;
}

// ---------------------------------------------------------------------------
// In-season response payloads
// ---------------------------------------------------------------------------

export interface LineupSlotEntry {
  slot: string;
  player_id: string;
  name: string;
  position: Position;
  projected: number;
  ceiling: number;
  floor: number;
  injury_tag: string | null;
  weather: string | null;
}

export interface LineupOptimizationPayload {
  starters: LineupSlotEntry[];
  bench: LineupSlotEntry[];
  total_projected: number;
  total_ceiling: number;
  total_floor: number;
  solver_used: string;
}

export interface TradeEvaluationPayload {
  pre_trade_utility: number;
  post_trade_utility: number;
  delta_utility: number;
  pre_win_probability: number;
  post_win_probability: number;
  delta_win_probability: number;
  opponent_pre_utility: number;
  opponent_post_utility: number;
  opponent_delta_utility: number;
  recommended: boolean;
}

export interface FaabBidEntry {
  player_id: string;
  name: string;
  position: Position;
  ros_projection: number;
  ros_dvorp: number;
  replacement: number;
  recommended_bid: number;
  user_need_factor: number;
  rival_pressure: number;
}

export interface FaabBidsPayload {
  bids: FaabBidEntry[];
}

// ---------------------------------------------------------------------------
// Response envelope
// ---------------------------------------------------------------------------

export interface OkResponse<T> {
  ok: true;
  data: T;
}

export interface ErrResponse {
  ok: false;
  error: string;
  code: string;
}

export type ResponsePayload<T> = OkResponse<T> | ErrResponse;

// ---------------------------------------------------------------------------
// Engine status (from Tauri sidecar commands)
// ---------------------------------------------------------------------------

export interface EngineStatus {
  running: boolean;
  healthy: boolean;
  pid: number | null;
  wsUrl: string;
}

// ---------------------------------------------------------------------------
// UI layer types (normalized, camelCase records used by React components)
// ---------------------------------------------------------------------------

/** Seasonal format selector surfaced through the league configuration modal. */
export type DraftFormat = "redraft" | "dynasty";

/** Scoring preset selector surfaced through the league configuration modal. */
export type ScoringFormat = "standard" | "half-ppr" | "full-ppr";

/** A drafting team, derived from `LeagueConfig.teams_count`. */
export interface Team {
  index: number;
  name: string;
}

/** Compact player metadata kept in the store's name lookup index. */
export interface PlayerIndexEntry {
  name: string;
  position: Position;
  team: string;
}

/**
 * Enriched player record shown in the available player pool and player list.
 *
 * Built by normalizing a `Recommendation`. The dynamic replacement value is
 * derived directly from the DVORP identity `fantasy_points - dvorp`.
 */
export interface Player {
  playerId: string;
  name: string;
  position: Position;
  team: string;
  adp: number | null;
  byeWeek: number;
  fantasyPoints: number;
  xfp: number | null;
  wopr: number | null;
  dvorp: number;
  replacementValue: number;
  pMb: number;
  utility: number;
}
