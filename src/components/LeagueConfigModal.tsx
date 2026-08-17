import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Settings, X } from "lucide-react";

import {
  DEFAULT_LEAGUE_CONFIG,
  DraftFormat,
  ScoringFormat,
  SyncLeagueConfigPayload,
} from "../types/protocol";
import { useDraftStore } from "../store/useDraftStore";

interface LeagueConfigModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Get the scoring `rec` value for a PPR preset.
 */
function pprValue(preset: ScoringFormat): number {
  switch (preset) {
    case "standard":
      return 0;
    case "half-ppr":
      return 0.5;
    case "full-ppr":
      return 1;
  }
}

/**
 * Dynamic league configuration modal.
 *
 * Controls:
 * - Redraft vs Dynasty
 * - Scoring preset (Standard / Half-PPR / Full-PPR)
 * - TE-Premium bonus
 * - Superflex roster slot
 * - Team count
 */
export default function LeagueConfigModal({
  open,
  onClose,
}: LeagueConfigModalProps) {
  const syncLeagueConfig = useDraftStore((s) => s.syncLeagueConfig);
  const loading = useDraftStore((s) => s.loading);
  const error = useDraftStore((s) => s.error);

  const [format, setFormat] = useState<DraftFormat>("redraft");
  const [scoring, setScoring] = useState<ScoringFormat>("full-ppr");
  const [tePremium, setTePremium] = useState(false);
  const [superflex, setSuperflex] = useState(false);
  const [teamsCount, setTeamsCount] = useState(
    DEFAULT_LEAGUE_CONFIG.teams_count,
  );

  // Reset to defaults whenever the modal is opened.
  useEffect(() => {
    if (!open) return;
    setFormat("redraft");
    setScoring("full-ppr");
    setTePremium(false);
    setSuperflex(false);
    setTeamsCount(DEFAULT_LEAGUE_CONFIG.teams_count);
  }, [open]);

  if (!open) return null;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();

    const payload: SyncLeagueConfigPayload = {
      name: `${format === "dynasty" ? "Dynasty" : "Redraft"} · ${
        scoring === "full-ppr" ? "Full-PPR" : scoring === "half-ppr" ? "Half-PPR" : "Standard"
      }${tePremium ? " · TE-Premium" : ""}${superflex ? " · Superflex" : ""}`,
      teams_count: teamsCount,
      scoring: {
        pass_yd: 0.04,
        pass_td: 4.0,
        pass_int: -2.0,
        rush_yd: 0.1,
        rush_td: 6.0,
        rec: pprValue(scoring),
        rec_yd: 0.1,
        rec_td: 6.0,
        te_rec_bonus: tePremium ? 1.0 : 0.0,
        fumble_lost: -2.0,
        two_pt: 2.0,
      },
      roster_slots: {
        QB: 1,
        RB: 2,
        WR: 2,
        TE: 1,
        FLEX: 1,
        SUPERFLEX: superflex ? 1 : 0,
        BENCH: 6,
        K: 0,
        DST: 0,
      },
      user_team_index: 0,
      allow_network: false,
    };

    await syncLeagueConfig(payload);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-white/10 bg-slate-900 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 text-slate-300" />
            <h2 className="text-lg font-semibold text-white">
              League Configuration
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5 px-5 py-5">
          {/* Format */}
          <Field label="Season Format">
            <Segmented
              options={[
                { value: "redraft", label: "Redraft" },
                { value: "dynasty", label: "Dynasty" },
              ]}
              value={format}
              onChange={(value) => setFormat(value as DraftFormat)}
            />
          </Field>

          {/* Scoring */}
          <Field label="Scoring">
            <Segmented
              options={[
                { value: "standard", label: "Standard" },
                { value: "half-ppr", label: "Half-PPR" },
                { value: "full-ppr", label: "Full-PPR" },
              ]}
              value={scoring}
              onChange={(value) => setScoring(value as ScoringFormat)}
            />
          </Field>

          {/* TE Premium */}
          <Toggle
            label="TE-Premium bonus"
            description="Award an extra point per tight-end reception."
            checked={tePremium}
            onChange={setTePremium}
          />

          {/* Superflex */}
          <Toggle
            label="Superflex roster slot"
            description="Add a QB-eligible flex slot to every roster."
            checked={superflex}
            onChange={setSuperflex}
          />

          {/* Team count */}
          <Field label={`Teams (${teamsCount})`}>
            <input
              type="range"
              min={8}
              max={16}
              step={2}
              value={teamsCount}
              onChange={(event) => setTeamsCount(Number(event.target.value))}
              className="w-full accent-emerald-500"
            />
            <div className="mt-1 flex justify-between text-xs text-slate-500">
              <span>8 teams</span>
              <span>12 teams</span>
              <span>16 teams</span>
            </div>
          </Field>

          {error && (
            <p className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-white/10 px-4 py-2 text-sm font-medium text-slate-300 transition-colors hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "Applying…" : "Apply Config"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small building blocks
// ---------------------------------------------------------------------------

interface FieldProps {
  label: string;
  children: ReactNode;
}

function Field({ label, children }: FieldProps) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-300">
        {label}
      </label>
      {children}
    </div>
  );
}

interface SegmentedOption {
  value: string;
  label: string;
}

interface SegmentedProps {
  options: SegmentedOption[];
  value: string;
  onChange: (value: string) => void;
}

function Segmented({ options, value, onChange }: SegmentedProps) {
  return (
    <div className="grid grid-flow-col gap-1 rounded-lg border border-white/10 bg-slate-950/60 p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            value === option.value
              ? "bg-emerald-500/20 text-emerald-300"
              : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

interface ToggleProps {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}

function Toggle({ label, description, checked, onChange }: ToggleProps) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between rounded-lg border border-white/10 bg-slate-950/40 px-4 py-3 text-left transition-colors hover:bg-slate-950/70"
    >
      <div>
        <div className="text-sm font-medium text-slate-200">{label}</div>
        <div className="mt-0.5 text-xs text-slate-500">{description}</div>
      </div>
      <span
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
          checked ? "bg-emerald-500" : "bg-slate-700"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </span>
    </button>
  );
}

