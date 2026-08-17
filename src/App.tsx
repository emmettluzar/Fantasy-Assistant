import { useEffect, useState, type ReactNode } from "react";
import {
  Loader,
  Radio,
  RefreshCw,
  Settings,
  Sparkles,
  Trophy,
  Users,
  Wifi,
  WifiOff,
  X,
  Zap,
} from "lucide-react";

import DraftBoard from "./components/DraftBoard";
import LeagueConfigModal from "./components/LeagueConfigModal";
import PlayerList from "./components/PlayerList";
import RecommendationCard from "./components/RecommendationCard";
import { useDraftStore } from "./store/useDraftStore";
import { IpcConnectionState } from "./lib/ipcClient";

function App() {
  const engine = useDraftStore((s) => s.engine);
  const connection = useDraftStore((s) => s.connection);
  const config = useDraftStore((s) => s.config);
  const teams = useDraftStore((s) => s.teams);
  const draftedCount = useDraftStore((s) => s.draftedCount);
  const availableCount = useDraftStore((s) => s.availableCount);
  const rNext = useDraftStore((s) => s.rNext);
  const recommendations = useDraftStore((s) => s.recommendations);
  const loading = useDraftStore((s) => s.loading);
  const error = useDraftStore((s) => s.error);

  const startEngine = useDraftStore((s) => s.startEngine);
  const stopEngine = useDraftStore((s) => s.stopEngine);
  const refreshEngineStatus = useDraftStore((s) => s.refreshEngineStatus);
  const subscribeConnection = useDraftStore((s) => s.subscribeConnection);
  const subscribePicks = useDraftStore((s) => s.subscribePicks);
  const getRecommendations = useDraftStore((s) => s.getRecommendations);
  const resetDraft = useDraftStore((s) => s.resetDraft);

  const [configOpen, setConfigOpen] = useState(false);

  // Keep the store's WebSocket connection state subscribed for the badge.
  useEffect(() => subscribeConnection(), [subscribeConnection]);

  // Subscribe to live `PICK_UPDATE` pushes so picks streamed by the browser
  // extension / platform adapters update the board without a manual refresh.
  useEffect(() => subscribePicks(), [subscribePicks]);

  // Seed engine status on first mount.
  useEffect(() => {
    refreshEngineStatus();
  }, [refreshEngineStatus]);

  const top = recommendations[0];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-white/10 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
              <Trophy className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-base font-bold leading-tight text-white">
                Fantasy Draft Assistant
              </h1>
              <p className="text-xs text-slate-500">{config.name}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <SyncBadge state={connection} />

            {engine ? (
              <button
                type="button"
                onClick={() => (engine.running ? stopEngine() : startEngine())}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:bg-white/5"
                title={engine.running ? "Stop engine" : "Start engine"}
              >
                {engine.running ? (
                  <Radio className="h-4 w-4 animate-pulse text-emerald-400" />
                ) : (
                  <Zap className="h-4 w-4 text-slate-400" />
                )}
                <span>{engine.running ? "Running" : "Start"}</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={startEngine}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:bg-white/5"
              >
                <Zap className="h-4 w-4 text-slate-400" />
                <span>Start</span>
              </button>
            )}

            <button
              type="button"
              onClick={() => setConfigOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 transition-colors hover:bg-emerald-400"
            >
              <Settings className="h-4 w-4" />
              <span>Configure</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="mx-auto max-w-7xl px-4 py-6">
        {/* Stat strip */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat icon={<Users className="h-4 w-4" />} label="Teams" value={String(teams.length || "—")} />
          <Stat
            icon={<Trophy className="h-4 w-4" />}
            label="Drafted"
            value={String(draftedCount)}
          />
          <Stat
            icon={<Sparkles className="h-4 w-4" />}
            label="Available"
            value={String(availableCount)}
          />
          <Stat
            icon={<Radio className="h-4 w-4" />}
            label="Next Pick"
            value={rNext > 0 ? `#${Math.round(rNext)}` : "—"}
          />
        </div>

        {error && (
          <div className="mt-4 flex items-center justify-between rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            <span>{error}</span>
            <button
              type="button"
              onClick={() => getRecommendations({})}
              className="ml-3 inline-flex shrink-0 items-center gap-1 text-xs font-medium text-rose-200 hover:text-white"
            >
              <X className="h-3.5 w-3.5" />
              Dismiss
            </button>
          </div>
        )}

        {/* Recommendation + draft board */}
        <div className="mt-5 grid gap-5 lg:grid-cols-3">
          <section className="space-y-4 lg:col-span-1">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
                <Sparkles className="h-4 w-4 text-emerald-400" />
                Top Recommendation
              </h2>
              <button
                type="button"
                onClick={() => getRecommendations({})}
                disabled={loading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1 text-xs font-medium text-slate-300 transition-colors hover:bg-white/5 disabled:opacity-50"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
                Refresh
              </button>
            </div>

            {loading && !top ? (
              <div className="flex h-64 items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50">
                <Loader className="h-6 w-6 animate-spin text-emerald-400" />
              </div>
            ) : top ? (
              <RecommendationCard recommendation={top} />
            ) : (
              <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50 p-6 text-center">
                <Sparkles className="h-10 w-10 text-slate-600" />
                <p className="mt-3 text-sm text-slate-400">
                  No recommendations yet. Configure a league and refresh.
                </p>
              </div>
            )}

            {/* Controls */}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => resetDraft({ keep_config: true })}
                disabled={loading}
                className="flex-1 rounded-lg border border-white/10 px-3 py-2 text-xs font-medium text-slate-300 transition-colors hover:bg-white/5 disabled:opacity-50"
              >
                Reset Draft
              </button>
              <button
                type="button"
                onClick={() => setConfigOpen(true)}
                className="flex-1 rounded-lg border border-white/10 px-3 py-2 text-xs font-medium text-slate-300 transition-colors hover:bg-white/5"
              >
                Edit Config
              </button>
            </div>
          </section>

          {/* Draft board */}
          <section className="lg:col-span-2">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
              Draft Board
            </h2>
            <DraftBoard />
          </section>
        </div>

        {/* Player list */}
        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
            Available Players
          </h2>
          <PlayerList />
        </section>
      </main>

      <LeagueConfigModal open={configOpen} onClose={() => setConfigOpen(false)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small building blocks
// ---------------------------------------------------------------------------

interface StatProps {
  icon: ReactNode;
  label: string;
  value: string;
}

function Stat({ icon, label, value }: StatProps) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-slate-900/50 px-4 py-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/5 text-slate-400">
        {icon}
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-500">
          {label}
        </div>
        <div className="text-lg font-bold text-white">{value}</div>
      </div>
    </div>
  );
}

interface SyncBadgeProps {
  state: IpcConnectionState;
}

function SyncBadge({ state }: SyncBadgeProps) {
  const meta: Record<
    IpcConnectionState,
    { label: string; icon: ReactNode; className: string }
  > = {
    connecting: {
      label: "Connecting",
      icon: <Loader className="h-3.5 w-3.5 animate-spin" />,
      className: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    },
    connected: {
      label: "Synced",
      icon: <Wifi className="h-3.5 w-3.5" />,
      className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    },
    disconnected: {
      label: "Offline",
      icon: <WifiOff className="h-3.5 w-3.5" />,
      className: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    },
  };

  const current = meta[state];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium ${current.className}`}
    >
      {current.icon}
      {current.label}
    </span>
  );
}

export default App;