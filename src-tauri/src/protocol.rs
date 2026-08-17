//! IPC message schema for the Fantasy Draft Assistant bridge.
//!
//! This module is the Rust-side mirror of:
//!
//! * `src-python/protocol.py`  (Python / pydantic)
//! * `src/types/protocol.ts`   (TypeScript)
//!
//! The canonical wire format originates from the pydantic models in
//! `engine/models.py`, so scoring fields use snake_case JSON keys and roster
//! slots use UPPERCASE JSON keys. Frames on the wire use the envelope:
//!
//! ```json
//! {"type": "<TYPE>", "payload": { ... }, "request_id": "<id>"}
//! ```
//!
//! Most of these structs are the Rust-side schema mirror kept in lockstep with
//! `src-python/protocol.py` and `src/types/protocol.ts`. They are intentionally
//! retained for deserialization/validation of engine responses and future
//! typed IPC commands; disable dead-code warnings so the mirror stays exact.
#![allow(dead_code)]

use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// Transport constants
// ---------------------------------------------------------------------------

pub const DEFAULT_WS_URL: &str = "ws://127.0.0.1:8080";
pub const DEFAULT_HOST: &str = "127.0.0.1";
pub const DEFAULT_PORT: u16 = 8080;

pub const TYPE_SYNC: &str = "SYNC_LEAGUE_CONFIG";
pub const TYPE_PICK: &str = "DRAFT_PICK_MADE";
pub const TYPE_RECOMMEND: &str = "GET_RECOMMENDATIONS";
pub const TYPE_RESET: &str = "RESET_DRAFT";
pub const TYPE_RESPONSE: &str = "RESPONSE";

pub const DEFAULT_LIMIT: usize = 8;
pub const MAX_LIMIT: usize = 50;

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Envelope {
    #[serde(rename = "type")]
    pub message_type: String,
    #[serde(default)]
    pub request_id: String,
    pub payload: serde_json::Value,
}

impl Envelope {
    /// Build a request envelope from a typed payload.
    pub fn request(message_type: &str, request_id: &str, payload: impl Serialize) -> Self {
        let payload = serde_json::to_value(payload).unwrap_or(serde_json::Value::Null);
        Self {
            message_type: message_type.to_string(),
            request_id: request_id.to_string(),
            payload,
        }
    }
}

// ---------------------------------------------------------------------------
// Scoring rules (snake_case keys)
// ---------------------------------------------------------------------------

fn d_pass_yd() -> f64 {
    0.04
}
fn d_pass_td() -> f64 {
    4.0
}
fn d_pass_int() -> f64 {
    -2.0
}
fn d_rush_yd() -> f64 {
    0.1
}
fn d_rush_td() -> f64 {
    6.0
}
fn d_rec() -> f64 {
    0.0
}
fn d_rec_yd() -> f64 {
    0.1
}
fn d_rec_td() -> f64 {
    6.0
}
fn d_te_rec_bonus() -> f64 {
    0.0
}
fn d_fumble_lost() -> f64 {
    -2.0
}
fn d_two_pt() -> f64 {
    2.0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScoringRules {
    #[serde(default = "d_pass_yd")]
    pub pass_yd: f64,
    #[serde(default = "d_pass_td")]
    pub pass_td: f64,
    #[serde(default = "d_pass_int")]
    pub pass_int: f64,
    #[serde(default = "d_rush_yd")]
    pub rush_yd: f64,
    #[serde(default = "d_rush_td")]
    pub rush_td: f64,
    #[serde(default = "d_rec")]
    pub rec: f64,
    #[serde(default = "d_rec_yd")]
    pub rec_yd: f64,
    #[serde(default = "d_rec_td")]
    pub rec_td: f64,
    #[serde(default = "d_te_rec_bonus")]
    pub te_rec_bonus: f64,
    #[serde(default = "d_fumble_lost")]
    pub fumble_lost: f64,
    #[serde(default = "d_two_pt")]
    pub two_pt: f64,
}

// ---------------------------------------------------------------------------
// Roster settings (UPPERCASE keys)
// ---------------------------------------------------------------------------

fn d_qb() -> i32 {
    1
}
fn d_rb() -> i32 {
    2
}
fn d_wr() -> i32 {
    2
}
fn d_te() -> i32 {
    1
}
fn d_flex() -> i32 {
    1
}
fn d_superflex() -> i32 {
    0
}
fn d_bench() -> i32 {
    6
}
fn d_k() -> i32 {
    0
}
fn d_dst() -> i32 {
    0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RosterSettings {
    #[serde(rename = "QB", default = "d_qb")]
    pub qb: i32,
    #[serde(rename = "RB", default = "d_rb")]
    pub rb: i32,
    #[serde(rename = "WR", default = "d_wr")]
    pub wr: i32,
    #[serde(rename = "TE", default = "d_te")]
    pub te: i32,
    #[serde(rename = "FLEX", default = "d_flex")]
    pub flex: i32,
    #[serde(rename = "SUPERFLEX", default = "d_superflex")]
    pub superflex: i32,
    #[serde(rename = "BENCH", default = "d_bench")]
    pub bench: i32,
    #[serde(rename = "K", default = "d_k")]
    pub k: i32,
    #[serde(rename = "DST", default = "d_dst")]
    pub dst: i32,
}

// ---------------------------------------------------------------------------
// League configuration
// ---------------------------------------------------------------------------

fn d_name() -> String {
    "Custom".to_string()
}
fn d_teams_count() -> i32 {
    12
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LeagueConfig {
    #[serde(default = "d_name")]
    pub name: String,
    #[serde(default)]
    pub scoring: ScoringRules,
    #[serde(default)]
    pub roster_slots: RosterSettings,
    #[serde(default = "d_teams_count")]
    pub teams_count: i32,
}

impl Default for LeagueConfig {
    fn default() -> Self {
        Self {
            name: d_name(),
            scoring: ScoringRules::default(),
            roster_slots: RosterSettings::default(),
            teams_count: d_teams_count(),
        }
    }
}

impl Default for ScoringRules {
    fn default() -> Self {
        Self {
            pass_yd: d_pass_yd(),
            pass_td: d_pass_td(),
            pass_int: d_pass_int(),
            rush_yd: d_rush_yd(),
            rush_td: d_rush_td(),
            rec: d_rec(),
            rec_yd: d_rec_yd(),
            rec_td: d_rec_td(),
            te_rec_bonus: d_te_rec_bonus(),
            fumble_lost: d_fumble_lost(),
            two_pt: d_two_pt(),
        }
    }
}

impl Default for RosterSettings {
    fn default() -> Self {
        Self {
            qb: d_qb(),
            rb: d_rb(),
            wr: d_wr(),
            te: d_te(),
            flex: d_flex(),
            superflex: d_superflex(),
            bench: d_bench(),
            k: d_k(),
            dst: d_dst(),
        }
    }
}

// ---------------------------------------------------------------------------
// Message payloads
// ---------------------------------------------------------------------------

/// Payload for `SYNC_LEAGUE_CONFIG`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncLeagueConfigPayload {
    #[serde(flatten)]
    pub league: LeagueConfig,
    #[serde(default)]
    pub user_team_index: i32,
    #[serde(default)]
    pub allow_network: bool,
}

/// Payload for `GET_RECOMMENDATIONS`.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct GetRecommendationsPayload {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_team_index: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub r_next: Option<f64>,
    #[serde(default = "d_default_limit")]
    pub limit: usize,
}

fn d_default_limit() -> usize {
    DEFAULT_LIMIT
}

/// Payload for `DRAFT_PICK_MADE`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DraftPickMadePayload {
    pub pick_number: i32,
    pub round: i32,
    pub team_index: i32,
    pub player_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub position: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fantasy_points: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<f64>,
}

/// Payload for `RESET_DRAFT`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResetDraftPayload {
    #[serde(default = "d_keep_config")]
    pub keep_config: bool,
}

fn d_keep_config() -> bool {
    true
}

impl Default for ResetDraftPayload {
    fn default() -> Self {
        Self { keep_config: true }
    }
}

// ---------------------------------------------------------------------------
// Response payloads
// ---------------------------------------------------------------------------

/// A single recommendation returned by `GET_RECOMMENDATIONS`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Recommendation {
    pub player_id: String,
    pub name: String,
    pub position: String,
    #[serde(default)]
    pub team: String,
    #[serde(default)]
    pub adp: Option<f64>,
    #[serde(default)]
    pub bye_week: i32,
    #[serde(default)]
    pub fantasy_points: f64,
    #[serde(default)]
    pub dvorp: f64,
    #[serde(default)]
    pub p_mb: f64,
    #[serde(default)]
    pub r_need: f64,
    #[serde(default)]
    pub p_bye: f64,
    #[serde(default)]
    pub utility: f64,
}

/// `data` returned by `GET_RECOMMENDATIONS`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecommendationsPayload {
    pub user_team_index: i32,
    pub r_next: f64,
    pub available_count: usize,
    pub recommendations: Vec<Recommendation>,
}

/// A normalized draft event echoed back by `DRAFT_PICK_MADE`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PickEcho {
    pub pick_number: i32,
    pub round: i32,
    pub team_index: i32,
    pub player_id: String,
    pub position: String,
    #[serde(default)]
    pub fantasy_points: f64,
}

/// `data` returned by `DRAFT_PICK_MADE`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PickAcceptedPayload {
    pub pick: PickEcho,
    pub available_count: usize,
    #[serde(default)]
    pub baselines: BaselinesPayload,
    #[serde(default)]
    pub dvorp_updated: bool,
}

/// Positional replacement baselines.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct BaselinesPayload {
    #[serde(default)]
    pub replacements: std::collections::BTreeMap<String, f64>,
}

/// `data` returned by `SYNC_LEAGUE_CONFIG` and `RESET_DRAFT`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnakeBoardSnapshot {
    pub config: LeagueConfig,
    pub user_team_index: i32,
    pub drafted_count: usize,
    pub available_count: usize,
    #[serde(default)]
    pub picks: Vec<SnapshotPick>,
    #[serde(default)]
    pub user_owned: std::collections::BTreeMap<String, i32>,
}

/// A pick as serialized by the pydantic `DraftPick` model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnapshotPick {
    pub pick_number: i32,
    pub round: i32,
    pub team_index: i32,
    pub player_id: String,
    pub position: String,
    #[serde(default)]
    pub fantasy_points: f64,
    #[serde(default)]
    pub timestamp: Option<f64>,
}

// ---------------------------------------------------------------------------
// Response envelope helpers
// ---------------------------------------------------------------------------

/// The `payload` object of a `RESPONSE` envelope.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ResponsePayload {
    Ok { ok: bool, data: serde_json::Value },
    Err { ok: bool, error: String, code: String },
}