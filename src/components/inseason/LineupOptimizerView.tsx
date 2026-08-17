import { useMemo } from "react";
import { Loader, Play, Sparkles, Wind } from "lucide-react";

import { useInseasonStore } from "../../store/useInseasonStore";
import { LineupSlotEntry, RosterPlayerPayload } from "../../types/protocol";
import { formatNumber, POSITION_BG } from "../../lib/format";

/**
 * Optimal starting roster vs bench, powered by the MILP lineup optimizer.
 *
 * Sends a sample weekly roster (with injury/weather tags) to the engine and
 * renders the optimizer's chosen starters versus the bench, along with each
 * player's projected ceiling/floor and a one-click lineup export.
 */
export default function LineupOptimizerView() {
  const lineup = useInseasonStore((s) => s.lineup);
  const loading = useInseasonStore((s) => s.loading);
  const error = useInseasonStore((s) => s.error);
  const optimizeLineup = useInseasonStore((s) => s.optimizeLineup);

  const run = () => optimizeLineup({ roster: SAMPLE_ROSTER });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
            <Sparkles className="h-4 w-4 text-emerald-400" />
            Lineup Optimizer
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            MILP solver maximizing projected points while accounting for injury
            and weather penalties.
          </p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 transition-colors hover:bg-emerald-400 disabled:opacity-50"
        >
          <Play className="h-4 w-4" />
          Run Optimizer
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {loading && !lineup ? (
        <div className="flex h-64 items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50">
          <Loader className="h-6 w-6 animate-spin text-emerald-400" />
        </div>
      ) : lineup ? (
        <LineupResult
          starters={lineup.starters}
          bench={lineup.bench}
          totalProjected={lineup.total_projected}
          totalCeiling={lineup.total_ceiling}
          totalFloor={lineup.total_floor}
          solverUsed={lineup.solver_used}
        />
      ) : (
        <EmptyState
          title="No lineup optimized yet"
          hint="Run the optimizer to see your optimal starters versus bench."
          onRun={run}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result rendering
// ---------------------------------------------------------------------------

interface LineupResultProps {
  starters: LineupSlotEntry[];
  bench: LineupSlotEntry[];
  totalProjected: number;
  totalCeiling: number;
  totalFloor: number;
  solverUsed: string;
}

function LineupResult({
  starters,
  bench,
  totalProjected,
  totalCeiling,
  totalFloor,
  solverUsed,
}: LineupResultProps) {
  const exportText = useMemo(() => buildExport(starters), [starters]);

  const copyExport = () => {
    void navigator.clipboard?.writeText(exportText);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <TotalCard label="Projected" value={totalProjected} accent="text-emerald-300" />
        <TotalCard label="Ceiling" value={totalCeiling} accent="text-sky-300" />
        <TotalCard label="Floor" value={totalFloor} accent="text-amber-300" />
      </div>

      <div className="text-xs text-slate-500">
        Solver:{" "}
        <span className="font-semibold text-slate-300">{solverUsed}</span>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <SlotGroup title="Starters" slots={starters} />
        <SlotGroup title="Bench" slots={bench} />
      </div>

      <div className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-900/50 px-4 py-3">
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-xs text-slate-400">
          {exportText}
        </pre>
        <button
          type="button"
          onClick={copyExport}
          className="ml-3 shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:bg-white/5"
        >
          Copy
        </button>
      </div>
    </div>
  );
}

function SlotGroup({
  title,
  slots,
}: {
  title: string;
  slots: LineupSlotEntry[];
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-slate-900/50">
      <div className="border-b border-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
        {title}
      </div>
      <ul className="divide-y divide-white/5">
        {slots.map((slot) => (
          <SlotRow key={slot.slot + slot.player_id} slot={slot} />
        ))}
        {slots.length === 0 && (
          <li className="px-4 py-3 text-sm text-slate-500">No players</li>
        )}
      </ul>
    </div>
  );
}

function SlotRow({ slot }: { slot: LineupSlotEntry }) {
  return (
    <li className="flex items-center justify-between gap-3 px-4 py-2.5">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            {slot.slot}
          </span>
          <span
            className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-semibold ${POSITION_BG[slot.position]}`}
          >
            {slot.position}
          </span>
          {slot.injury_tag && (
            <span className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-rose-300">
              {slot.injury_tag}
            </span>
          )}
          {slot.weather && (
            <span className="inline-flex items-center gap-0.5 rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-sky-300">
              <Wind className="h-3 w-3" />
              {slot.weather}
            </span>
          )}
        </div>
        <div className="mt-0.5 truncate text-sm font-medium text-white">
          {slot.name}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3 text-right">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            Proj
          </div>
          <div className="text-sm font-bold text-emerald-300">
            {formatNumber(slot.projected)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            Ceil / Floor
          </div>
          <div className="text-xs text-slate-300">
            {formatNumber(slot.ceiling)} / {formatNumber(slot.floor)}
          </div>
        </div>
      </div>
    </li>
  );
}

function TotalCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/50 px-4 py-3 text-center">
      <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={`mt-0.5 text-lg font-bold ${accent}`}>
        {formatNumber(value)}
      </div>
    </div>
  );
}

function EmptyState({
  title,
  hint,
  onRun,
}: {
  title: string;
  hint: string;
  onRun: () => void;
}) {
  return (
    <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50 p-6 text-center">
      <Sparkles className="h-10 w-10 text-slate-600" />
      <p className="mt-3 text-sm font-medium text-slate-300">{title}</p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
      <button
        type="button"
        onClick={onRun}
        className="mt-4 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:bg-white/5"
      >
        Run optimizer with sample roster
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sample data + export helper
// ---------------------------------------------------------------------------

const SAMPLE_ROSTER: RosterPlayerPayload[] = [
  { player_id: "QB01", name: "QB Allen", position: "QB", fantasy_points: 24.1 },
  { player_id: "QB02", name: "QB Hurts", position: "QB", fantasy_points: 22.4, injury_tag: "Q" },
  { player_id: "RB01", name: "RB CMC", position: "RB", fantasy_points: 21.8 },
  { player_id: "RB02", name: "RB Henry", position: "RB", fantasy_points: 19.2 },
  { player_id: "RB03", name: "RB Walker", position: "RB", fantasy_points: 13.5, weather: "SNOW" },
  { player_id: "WR01", name: "WR Jefferson", position: "WR", fantasy_points: 20.6 },
  { player_id: "WR02", name: "WR Chase", position: "WR", fantasy_points: 19.4 },
  { player_id: "WR03", name: "WR Lamb", position: "WR", fantasy_points: 18.1 },
  { player_id: "WR04", name: "WR Hill", position: "WR", fantasy_points: 15.2, injury_tag: "Q" },
  { player_id: "TE01", name: "TE Kelce", position: "TE", fantasy_points: 15.7 },
  { player_id: "TE02", name: "TE McBride", position: "TE", fantasy_points: 12.3 },
  { player_id: "RB04", name: "RB Pollard", position: "RB", fantasy_points: 11.9 },
];

function buildExport(starters: LineupSlotEntry[]): string {
  const lines = starters.map(
    (s) => `${s.slot}: ${s.name} (${s.position}) ${formatNumber(s.projected)} pts`,
  );
  return lines.join("\n");
}