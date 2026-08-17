import { TrendingDown, TrendingUp, Zap } from "lucide-react";

import { Recommendation } from "../types/protocol";
import {
  formatNumber,
  formatUtility,
  POSITION_BG,
} from "../lib/format";

interface RecommendationCardProps {
  recommendation: Recommendation;
}

/**
 * Highlight the #1 recommended player with the decision utility score
 * U_i(t), a DVORP badge, a Make-It-Back probability meter, and xFP vs
 * actual regression indicators.
 */
export default function RecommendationCard({
  recommendation,
}: RecommendationCardProps) {
  const {
    name,
    position,
    team,
    adp,
    bye_week,
    fantasy_points,
    xfp,
    dvorp,
    p_mb,
    utility,
  } = recommendation;

  // The "regression" angle compares expected (xFP, opportunity-driven) value
  // against actual projected fantasy points. A positive DELTA means the
  // player is being drafted above their opportunity; a negative DELTA means
  // their projection already discounts the opportunity gap.
  const xfpKnown = xfp !== null && xfp !== undefined && !Number.isNaN(xfp);
  const delta = xfpKnown ? (xfp as number) - fantasy_points : null;
  const regressing = delta !== null && delta > 0;

  // Make-It-Back probability of being gone by your next pick (engine returns
  // the "gone" probability), which we expose as the availability risk meter.
  const availability = Math.round(p_mb * 100);
  const clamped = Math.max(0, Math.min(100, availability));

  return (
    <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/90 to-slate-950/95 p-5 shadow-xl shadow-black/40">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold ${POSITION_BG[position]}`}
            >
              {position}
            </span>
            <span className="truncate text-sm text-slate-400">{team}</span>
            <span className="text-xs text-slate-500">BYE {bye_week || "—"}</span>
          </div>
          <h2 className="mt-2 truncate text-2xl font-bold text-white">{name}</h2>
        </div>

        <div className="flex shrink-0 flex-col items-end">
          <span className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
            Utility U(t)
          </span>
          <span className="text-3xl font-black text-emerald-400">
            {formatUtility(utility)}
          </span>
        </div>
      </div>

      {/* Key metric strip */}
      <div className="mt-4 grid grid-cols-3 gap-3">
        <Metric
          label="DVORP"
          value={formatNumber(dvorp)}
          accent="text-emerald-300"
        />
        <Metric
          label="Proj. FP"
          value={formatNumber(fantasy_points)}
          accent="text-sky-300"
        />
        <Metric
          label="ADP"
          value={adp !== null && adp !== undefined ? String(Math.round(adp)) : "—"}
          accent="text-slate-300"
        />
      </div>

      {/* Make-It-Back probability meter */}
      <div className="mt-5">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-slate-300">
            Make-It-Back risk
          </span>
          <span className="font-semibold text-amber-300">{clamped}%</span>
        </div>
        <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-amber-500 to-rose-500 transition-all duration-500"
            style={{ width: `${clamped}%` }}
          />
        </div>
        <p className="mt-1.5 text-[11px] leading-snug text-slate-500">
          Probability this player is already gone by your next pick.
        </p>
      </div>

      {/* xFP vs Actual regression indicators */}
      <div className="mt-5 flex items-center justify-between rounded-xl border border-white/5 bg-white/5 px-3 py-2.5">
        <div className="flex items-center gap-2 text-xs text-slate-300">
          {regressing ? (
            <TrendingDown className="h-4 w-4 text-rose-400" />
          ) : (
            <TrendingUp className="h-4 w-4 text-emerald-400" />
          )}
          <span>xFP vs Actual</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-400">
            xFP {xfpKnown ? formatNumber(xfp) : "—"}
          </span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-300">
            Act {formatNumber(fantasy_points)}
          </span>
          <span
            className={`ml-1 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-semibold ${
              regressing
                ? "bg-rose-500/15 text-rose-300"
                : "bg-emerald-500/15 text-emerald-300"
            }`}
          >
            <Zap className="h-3 w-3" />
            {delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`}
          </span>
        </div>
      </div>
    </div>
  );
}

interface MetricProps {
  label: string;
  value: string;
  accent: string;
}

function Metric({ label, value, accent }: MetricProps) {
  return (
    <div className="rounded-lg border border-white/5 bg-white/5 px-3 py-2 text-center">
      <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={`mt-0.5 text-base font-bold ${accent}`}>{value}</div>
    </div>
  );
}