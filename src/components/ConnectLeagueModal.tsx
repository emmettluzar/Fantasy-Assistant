import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link2, Loader, RefreshCw, X } from "lucide-react";

import { useDraftStore } from "../store/useDraftStore";
import { PlatformName, SyncPlatformLeaguePayload } from "../types/protocol";

interface ConnectLeagueModalProps {
  open: boolean;
  onClose: () => void;
}

interface SleeperLeague {
  league_id?: string;
  name?: string;
}

interface SleeperTeam {
  index: number;
  name: string;
}

/** Current NFL season year used for Sleeper league lookups. */
function sleeperSeasonYear(): number {
  return new Date().getFullYear();
}

/**
 * Platform connection modal.
 *
 * Three tabs:
 * - Sleeper: username -> "Fetch Leagues" -> league -> user team.
 * - ESPN: league id, season, optional ``espn_s2`` + ``SWID`` cookies.
 * - Yahoo: league id + OAuth key.
 *
 * "Save & Sync" sends a ``SYNC_PLATFORM_LEAGUE`` frame through the store,
 * which delegates to the Python sidecar and populates rosters + scoring.
 */
export default function ConnectLeagueModal({
  open,
  onClose,
}: ConnectLeagueModalProps) {
  const syncPlatformLeague = useDraftStore((s) => s.syncPlatformLeague);
  const loading = useDraftStore((s) => s.loading);
  const error = useDraftStore((s) => s.error);

  const [tab, setTab] = useState<PlatformName>("sleeper");

  // Sleeper
  const [sleeperUsername, setSleeperUsername] = useState("");
  const [sleeperLeagues, setSleeperLeagues] = useState<SleeperLeague[]>([]);
  const [sleeperLeagueId, setSleeperLeagueId] = useState("");
  const [sleeperTeams, setSleeperTeams] = useState<SleeperTeam[]>([]);
  const [sleeperTeamIndex, setSleeperTeamIndex] = useState(0);
  const [sleeperBusy, setSleeperBusy] = useState(false);
  const [sleeperError, setSleeperError] = useState<string | null>(null);

  // ESPN
  const [espnLeagueId, setEspnLeagueId] = useState("");
  const [espnYear, setEspnYear] = useState(String(sleeperSeasonYear()));
  const [espnS2, setEspnS2] = useState("");
  const [espnSwid, setEspnSwid] = useState("");

  // Yahoo
  const [yahooLeagueId, setYahooLeagueId] = useState("");
  const [yahooOauthKey, setYahooOauthKey] = useState("");

  // Reset local form state whenever the modal is opened.
  useEffect(() => {
    if (!open) return;
    setTab("sleeper");
    setSleeperUsername("");
    setSleeperLeagues([]);
    setSleeperLeagueId("");
    setSleeperTeams([]);
    setSleeperTeamIndex(0);
    setSleeperBusy(false);
    setSleeperError(null);
    setEspnLeagueId("");
    setEspnYear(String(sleeperSeasonYear()));
    setEspnS2("");
    setEspnSwid("");
    setYahooLeagueId("");
    setYahooOauthKey("");
  }, [open]);

  if (!open) return null;

  const fetchSleeperLeagues = async () => {
    const username = sleeperUsername.trim();
    if (!username) return;
    setSleeperBusy(true);
    setSleeperError(null);
    try {
      const season = sleeperSeasonYear();
      const response = await fetch(
        `https://api.sleeper.app/v1/user/${encodeURIComponent(
          username,
        )}/leagues/nfl/${season}`,
      );
      if (!response.ok) {
        throw new Error(`Sleeper request failed (${response.status})`);
      }
      const data = (await response.json()) as unknown;
      const leagues: SleeperLeague[] = Array.isArray(data)
        ? (data as SleeperLeague[])
        : [];
      setSleeperLeagues(leagues);
      setSleeperLeagueId("");
      setSleeperTeams([]);
      setSleeperTeamIndex(0);
      if (leagues.length === 0) {
        setSleeperError("No leagues found for this username.");
      }
    } catch (err) {
      setSleeperError(err instanceof Error ? err.message : String(err));
    } finally {
      setSleeperBusy(false);
    }
  };

  const fetchSleeperTeams = async (leagueId: string) => {
    setSleeperLeagueId(leagueId);
    setSleeperTeams([]);
    setSleeperTeamIndex(0);
    if (!leagueId) return;
    setSleeperBusy(true);
    setSleeperError(null);
    try {
      const response = await fetch(
        `https://api.sleeper.app/v1/league/${encodeURIComponent(leagueId)}/rosters`,
      );
      if (!response.ok) {
        throw new Error(`Sleeper request failed (${response.status})`);
      }
      const data = (await response.json()) as unknown;
      const rosters: unknown[] = Array.isArray(data) ? data : [];
      const teams: SleeperTeam[] = rosters.map((roster, index) => {
        const item = (roster ?? {}) as Record<string, unknown>;
        const metadata = (item.metadata ?? {}) as Record<string, unknown>;
        const name =
          (metadata.team_name as string) ||
          (item.owner_id as string) ||
          `Team ${index + 1}`;
        return { index, name: String(name) };
      });
      setSleeperTeams(teams);
    } catch (err) {
      setSleeperError(err instanceof Error ? err.message : String(err));
    } finally {
      setSleeperBusy(false);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();

    let payload: SyncPlatformLeaguePayload;
    if (tab === "sleeper") {
      payload = {
        platform: "sleeper",
        league_id: sleeperLeagueId.trim() || undefined,
        user_team_index: sleeperTeamIndex,
      };
    } else if (tab === "espn") {
      const year = Number.parseInt(espnYear, 10);
      payload = {
        platform: "espn",
        league_id: espnLeagueId.trim() || undefined,
        year: Number.isFinite(year) ? year : undefined,
        espn_s2: espnS2.trim() || undefined,
        swid: espnSwid.trim() || undefined,
      };
    } else {
      payload = {
        platform: "yahoo",
        league_id: yahooLeagueId.trim() || undefined,
        oauth_key: yahooOauthKey.trim() || undefined,
      };
    }

    await syncPlatformLeague(payload);
    onClose();
  };

  const canSave =
    tab === "sleeper"
      ? Boolean(sleeperLeagueId)
      : tab === "espn"
        ? Boolean(espnLeagueId.trim())
        : Boolean(yahooLeagueId.trim());

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
            <Link2 className="h-5 w-5 text-slate-300" />
            <h2 className="text-lg font-semibold text-white">Connect League</h2>
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

        {/* Platform tabs */}
        <div className="px-5 pt-5">
          <Segmented
            options={[
              { value: "sleeper", label: "Sleeper" },
              { value: "espn", label: "ESPN" },
              { value: "yahoo", label: "Yahoo" },
            ]}
            value={tab}
            onChange={(value) => setTab(value as PlatformName)}
          />
        </div>

        <form onSubmit={handleSubmit} className="space-y-5 px-5 py-5">
          {tab === "sleeper" && (
            <div className="space-y-4">
              <Field label="Sleeper Username">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={sleeperUsername}
                    onChange={(event) => setSleeperUsername(event.target.value)}
                    placeholder="e.g. emmettluzar"
                    className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={fetchSleeperLeagues}
                    disabled={sleeperBusy || !sleeperUsername.trim()}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-sm font-medium text-slate-200 transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {sleeperBusy ? (
                      <Loader className="h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="h-4 w-4" />
                    )}
                    Fetch Leagues
                  </button>
                </div>
              </Field>

              <Field label="League">
                <select
                  value={sleeperLeagueId}
                  onChange={(event) => void fetchSleeperTeams(event.target.value)}
                  disabled={sleeperLeagues.length === 0}
                  className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 focus:border-emerald-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">Select a league…</option>
                  {sleeperLeagues.map((league) => (
                    <option key={league.league_id} value={league.league_id ?? ""}>
                      {league.name ?? league.league_id ?? "Unnamed League"}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Your Team">
                <select
                  value={sleeperTeamIndex}
                  onChange={(event) => setSleeperTeamIndex(Number(event.target.value))}
                  disabled={sleeperTeams.length === 0}
                  className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 focus:border-emerald-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {sleeperTeams.length === 0 ? (
                    <option value={0}>Select a league first…</option>
                  ) : (
                    sleeperTeams.map((team) => (
                      <option key={team.index} value={team.index}>
                        {team.name}
                      </option>
                    ))
                  )}
                </select>
              </Field>

              {sleeperError && (
                <p className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
                  {sleeperError}
                </p>
              )}
            </div>
          )}

          {tab === "espn" && (
            <div className="space-y-4">
              <Field label="League ID">
                <input
                  type="text"
                  value={espnLeagueId}
                  onChange={(event) => setEspnLeagueId(event.target.value)}
                  placeholder="e.g. 123456"
                  className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
                />
              </Field>
              <Field label="Season (Year)">
                <input
                  type="number"
                  value={espnYear}
                  onChange={(event) => setEspnYear(event.target.value)}
                  min={2000}
                  max={2100}
                  className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 focus:border-emerald-500 focus:outline-none"
                />
              </Field>
              <Field label="espn_s2 (optional)">
                <input
                  type="text"
                  value={espnS2}
                  onChange={(event) => setEspnS2(event.target.value)}
                  placeholder="Private league session cookie"
                  className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
                />
              </Field>
              <Field label="SWID (optional)">
                <input
                  type="text"
                  value={espnSwid}
                  onChange={(event) => setEspnSwid(event.target.value)}
                  placeholder="Private league identity cookie"
                  className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
                />
              </Field>
            </div>
          )}

          {tab === "yahoo" && (
            <div className="space-y-4">
              <Field label="League ID">
                <input
                  type="text"
                  value={yahooLeagueId}
                  onChange={(event) => setYahooLeagueId(event.target.value)}
                  placeholder="e.g. 423.l.123456"
                  className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
                />
              </Field>
              <Field label="OAuth Key">
                <input
                  type="text"
                  value={yahooOauthKey}
                  onChange={(event) => setYahooOauthKey(event.target.value)}
                  placeholder="YFPY OAuth credentials key"
                  className="w-full rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
                />
              </Field>
            </div>
          )}

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
              disabled={loading || !canSave}
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "Syncing…" : "Save & Sync"}
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