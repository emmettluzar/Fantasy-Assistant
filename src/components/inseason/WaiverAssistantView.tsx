import { Loader, RefreshCw, TrendingUp } from "lucide-react";

import { useInseasonStore } from "../../store/useInseasonStore";
import {
  CalculateFaabBidsPayload,
  FaabBidEntry,
  Position,
} from "../../types/protocol";
import { formatNumber, POSITION_BG } from "../../lib/format";

/**
 * Ranked free-agent table with recommended FAAB dollar bids.
 *
 * Sends a sample free-agent pool to the engine, which computes rest-of-season
 * DVORP and converts it into an optimal FAAB bid accounting for budget, need,
 * and rival competition.
 */
export default function WaiverAssistantView() {
  const faabBids = useInseasonStore((s) => s.faabBids);
  const loading = useInseasonStore((s) => s.loading);
  const error = useInseasonStore((s) => s.error);
  const calculateFaabBids = useInseasonStore((s) => s.calculateFaabBids);

  const run = () => calculateFaabBids(SAMPLE_PAYLOAD);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
            <TrendingUp className="h-4 w-4 text-emerald-400" />
            Waiver Assistant
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Rest-of-season DVORP rankings with optimal FAAB bid suggestions.
          </p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 transition-colors hover:bg-emerald-400 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Calculate Bids
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {loading && !faabBids ? (
        <div className="flex h-64 items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50">
          <Loader className="h-6 w-6 animate-spin text-emerald-400" />
        </div>
      ) : faabBids && faabBids.bids.length > 0 ? (
        <BidsTable bids={faabBids.bids} />
      ) : (
        <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50 p-6 text-center">
          <TrendingUp className="h-10 w-10 text-slate-600" />
          <p className="mt-3 text-sm text-slate-400">
            No waiver bids yet. Run the calculator to rank available free agents.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

function BidsTable({ bids }: { bids: FaabBidEntry[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-slate-900/50">
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-slate-500">
              <th className="px-3 py-2">Player</th>
              <th className="px-3 py-2">Pos</th>
              <th className="px-3 py-2">ROS Proj</th>
              <th className="px-3 py-2">ROS DVORP</th>
              <th className="px-3 py-2">Replacement</th>
              <th className="px-3 py-2">Need</th>
              <th className="px-3 py-2">Rival</th>
              <th className="px-3 py-2">Bid</th>
            </tr>
          </thead>
          <tbody>
            {bids.map((bid) => (
              <BidRow key={bid.player_id} bid={bid} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BidRow({ bid }: { bid: FaabBidEntry }) {
  return (
    <tr className="border-b border-white/5 transition-colors hover:bg-white/5">
      <td className="px-3 py-2 font-medium text-white">{bid.name}</td>
      <td className="px-3 py-2">
        <span
          className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-semibold ${POSITION_BG[bid.position]}`}
        >
          {bid.position}
        </span>
      </td>
      <td className="px-3 py-2 text-slate-300">{formatNumber(bid.ros_projection)}</td>
      <td className="px-3 py-2 font-semibold text-emerald-300">
        {formatNumber(bid.ros_dvorp)}
      </td>
      <td className="px-3 py-2 text-slate-400">{formatNumber(bid.replacement)}</td>
      <td className="px-3 py-2 text-slate-300">{bid.user_need_factor.toFixed(2)}</td>
      <td className="px-3 py-2 text-slate-300">{bid.rival_pressure.toFixed(2)}</td>
      <td className="px-3 py-2">
        <span className="inline-flex items-center rounded-md bg-emerald-500/15 px-2 py-0.5 text-sm font-bold text-emerald-300">
          ${formatNumber(bid.recommended_bid)}
        </span>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Sample payload
// ---------------------------------------------------------------------------

const SAMPLE_PAYLOAD: CalculateFaabBidsPayload = {
  free_agents: [
    { player_id: "RB04", name: "RB Pollard", position: "RB", fantasy_points: 11.9 },
    { player_id: "WR04", name: "WR Hill", position: "WR", fantasy_points: 15.2 },
    { player_id: "TE02", name: "TE McBride", position: "TE", fantasy_points: 12.3 },
    { player_id: "QB03", name: "QB Cousins", position: "QB", fantasy_points: 18.0 },
  ],
  all_players: [
    { player_id: "RB01", name: "RB CMC", position: "RB", fantasy_points: 21.8 },
    { player_id: "RB02", name: "RB Henry", position: "RB", fantasy_points: 19.2 },
    { player_id: "RB03", name: "RB Walker", position: "RB", fantasy_points: 13.5 },
    { player_id: "RB04", name: "RB Pollard", position: "RB", fantasy_points: 11.9 },
    { player_id: "WR01", name: "WR Jefferson", position: "WR", fantasy_points: 20.6 },
    { player_id: "WR02", name: "WR Chase", position: "WR", fantasy_points: 19.4 },
    { player_id: "WR03", name: "WR Lamb", position: "WR", fantasy_points: 18.1 },
    { player_id: "WR04", name: "WR Hill", position: "WR", fantasy_points: 15.2 },
    { player_id: "TE01", name: "TE Kelce", position: "TE", fantasy_points: 15.7 },
    { player_id: "TE02", name: "TE McBride", position: "TE", fantasy_points: 12.3 },
    { player_id: "QB01", name: "QB Allen", position: "QB", fantasy_points: 24.1 },
    { player_id: "QB02", name: "QB Hurts", position: "QB", fantasy_points: 22.4 },
    { player_id: "QB03", name: "QB Cousins", position: "QB", fantasy_points: 18.0 },
  ],
  current_week: 6,
  user_budget: 72,
  roster_need: { RB: 1, WR: 1 } as Record<Position, number>,
  rival_need_by_pos: { RB: 3, WR: 2, TE: 1 } as Record<Position, number>,
  rival_faab: [80, 55, 91, 43, 67, 12, 74, 30, 88, 51, 22],
};