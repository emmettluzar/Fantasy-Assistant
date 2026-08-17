import { Loader, Scale, TrendingDown, TrendingUp } from "lucide-react";

import { useInseasonStore } from "../../store/useInseasonStore";
import {
  EvaluateTradePayload,
  RosterPlayerPayload,
} from "../../types/protocol";

/**
 * Side-by-side trade evaluator showing pre/post trade win-probability impact.
 *
 * Sends a sample two-team trade to the engine and renders the delta utility
 * plus win-probability change, with a clear accept/reject recommendation.
 */
export default function TradeAnalyzerView() {
  const trade = useInseasonStore((s) => s.trade);
  const loading = useInseasonStore((s) => s.loading);
  const error = useInseasonStore((s) => s.error);
  const evaluateTrade = useInseasonStore((s) => s.evaluateTrade);

  const run = () => evaluateTrade(SAMPLE_PAYLOAD);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
            <Scale className="h-4 w-4 text-emerald-400" />
            Trade Analyzer
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Delta utility across remaining regular season and playoff matchups.
          </p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 transition-colors hover:bg-emerald-400 disabled:opacity-50"
        >
          Evaluate Trade
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {loading && !trade ? (
        <div className="flex h-64 items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50">
          <Loader className="h-6 w-6 animate-spin text-emerald-400" />
        </div>
      ) : trade ? (
        <TradeResult trade={trade} />
      ) : (
        <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50 p-6 text-center">
          <Scale className="h-10 w-10 text-slate-600" />
          <p className="mt-3 text-sm text-slate-400">
            No trade evaluated yet. Run the analyzer on the sample two-team swap.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result
// ---------------------------------------------------------------------------

interface TradeResultProps {
  trade: {
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
  };
}

function TradeResult({ trade }: TradeResultProps) {
  const deltaWin = trade.delta_win_probability * 100;
  const favorable = trade.delta_utility > 0;

  return (
    <div className="space-y-4">
      <div
        className={`flex items-center justify-between rounded-2xl border px-4 py-3 ${
          trade.recommended
            ? "border-emerald-500/30 bg-emerald-500/10"
            : "border-rose-500/30 bg-rose-500/10"
        }`}
      >
        <div className="flex items-center gap-2">
          {favorable ? (
            <TrendingUp className="h-5 w-5 text-emerald-400" />
          ) : (
            <TrendingDown className="h-5 w-5 text-rose-400" />
          )}
          <span className="text-sm font-semibold">
            {trade.recommended
              ? "Accept — trade improves your team"
              : "Reject — trade hurts your team"}
          </span>
        </div>
        <span
          className={`text-2xl font-black ${
            favorable ? "text-emerald-400" : "text-rose-400"
          }`}
        >
          {trade.delta_utility >= 0 ? "+" : ""}
          {trade.delta_utility.toFixed(2)}
        </span>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <UtilityCard
          title="Your Team"
          pre={trade.pre_trade_utility}
          post={trade.post_trade_utility}
          delta={trade.delta_utility}
        />
        <UtilityCard
          title="Opponent"
          pre={trade.opponent_pre_utility}
          post={trade.opponent_post_utility}
          delta={trade.opponent_delta_utility}
        />
      </div>

      <div className="rounded-2xl border border-white/10 bg-slate-900/50 p-4">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Win Probability Impact
        </div>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-500">Before</div>
            <div className="text-lg font-bold text-slate-200">
              {(trade.pre_win_probability * 100).toFixed(1)}%
            </div>
          </div>
          <div className="h-px flex-1 bg-white/10" />
          <div>
            <div className="text-xs text-slate-500">After</div>
            <div className="text-lg font-bold text-slate-200">
              {(trade.post_win_probability * 100).toFixed(1)}%
            </div>
          </div>
          <div
            className={`ml-4 rounded-lg px-3 py-2 text-sm font-bold ${
              deltaWin >= 0
                ? "bg-emerald-500/15 text-emerald-300"
                : "bg-rose-500/15 text-rose-300"
            }`}
          >
            {deltaWin >= 0 ? "+" : ""}
            {deltaWin.toFixed(1)} pts
          </div>
        </div>
      </div>
    </div>
  );
}

function UtilityCard({
  title,
  pre,
  post,
  delta,
}: {
  title: string;
  pre: number;
  post: number;
  delta: number;
}) {
  const positive = delta >= 0;
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/50 p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
        {title}
      </div>
      <div className="flex items-end justify-between">
        <div>
          <div className="text-xs text-slate-500">Pre</div>
          <div className="text-xl font-bold text-slate-200">{pre.toFixed(2)}</div>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">Post</div>
          <div className="text-xl font-bold text-slate-200">{post.toFixed(2)}</div>
        </div>
      </div>
      <div
        className={`mt-3 inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold ${
          positive ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"
        }`}
      >
        {positive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
        {delta >= 0 ? "+" : ""}
        {delta.toFixed(2)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sample payload
// ---------------------------------------------------------------------------

const SAMPLE_USER_ROSTER: RosterPlayerPayload[] = [
  { player_id: "QB01", name: "QB Allen", position: "QB", fantasy_points: 24.1 },
  { player_id: "RB01", name: "RB CMC", position: "RB", fantasy_points: 21.8 },
  { player_id: "RB02", name: "RB Henry", position: "RB", fantasy_points: 19.2 },
  { player_id: "RB04", name: "RB Pollard", position: "RB", fantasy_points: 11.9 },
  { player_id: "WR01", name: "WR Jefferson", position: "WR", fantasy_points: 20.6 },
  { player_id: "WR03", name: "WR Lamb", position: "WR", fantasy_points: 18.1 },
  { player_id: "TE01", name: "TE Kelce", position: "TE", fantasy_points: 15.7 },
];

const SAMPLE_OPPONENT_ROSTER: RosterPlayerPayload[] = [
  { player_id: "QB02", name: "QB Hurts", position: "QB", fantasy_points: 22.4 },
  { player_id: "RB03", name: "RB Walker", position: "RB", fantasy_points: 13.5 },
  { player_id: "WR02", name: "WR Chase", position: "WR", fantasy_points: 19.4 },
  { player_id: "WR04", name: "WR Hill", position: "WR", fantasy_points: 15.2 },
  { player_id: "TE02", name: "TE McBride", position: "TE", fantasy_points: 12.3 },
];

const SAMPLE_PAYLOAD: EvaluateTradePayload = {
  user_roster: SAMPLE_USER_ROSTER,
  opponent_roster: SAMPLE_OPPONENT_ROSTER,
  user_gives: ["RB04"],
  user_receives: ["WR02"],
  current_week: 6,
};