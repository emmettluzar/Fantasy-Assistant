import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import { useDraftStore } from "../store/useDraftStore";
import { Player, Position } from "../types/protocol";
import {
  formatNumber,
  formatUtility,
  POSITION_BG,
} from "../lib/format";

type SortKey = "utility" | "dvorp" | "adp" | "xfp" | "wopr";

const POSITION_FILTERS: ("ALL" | Position)[] = [
  "ALL",
  "QB",
  "RB",
  "WR",
  "TE",
  "K",
  "DST",
];

/**
 * Searchable, filterable player table showing xFP, WOPR, ADP, and dynamic
 * replacement value for the available player pool.
 */
export default function PlayerList() {
  const playerPool = useDraftStore((s) => s.playerPool);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState<"ALL" | Position>("ALL");
  const [sortKey, setSortKey] = useState<SortKey>("utility");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = playerPool.filter((player) => {
      const matchesPosition =
        position === "ALL" || player.position === position;
      const matchesQuery =
        q.length === 0 ||
        player.name.toLowerCase().includes(q) ||
        player.team.toLowerCase().includes(q) ||
        player.playerId.toLowerCase().includes(q);
      return matchesPosition && matchesQuery;
    });

    return rows.sort((a, b) => sortValue(b, sortKey) - sortValue(a, sortKey));
  }, [playerPool, query, position, sortKey]);

  if (playerPool.length === 0) {
    return (
      <div className="rounded-2xl border border-white/10 bg-slate-900/50 p-6 text-center text-sm text-slate-400">
        No players available. Configure a league to load the projection pool.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-slate-900/50">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 border-b border-white/10 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search players or teams…"
            className="w-full rounded-lg border border-white/10 bg-slate-950/60 py-2 pl-8 pr-3 text-sm text-white placeholder:text-slate-500 focus:border-emerald-500/50 focus:outline-none"
          />
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {POSITION_FILTERS.map((pos) => (
            <button
              key={pos}
              type="button"
              onClick={() => setPosition(pos)}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                position === pos
                  ? "bg-emerald-500/20 text-emerald-300"
                  : "bg-slate-800/60 text-slate-400 hover:text-slate-200"
              }`}
            >
              {pos}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-slate-500">
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Player
              </th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Pos
              </th>
              <SortableHeader
                label="xFP"
                sortKey="xfp"
                active={sortKey}
                onClick={setSortKey}
              />
              <SortableHeader
                label="WOPR"
                sortKey="wopr"
                active={sortKey}
                onClick={setSortKey}
              />
              <SortableHeader
                label="ADP"
                sortKey="adp"
                active={sortKey}
                onClick={setSortKey}
              />
              <SortableHeader
                label="Repl. Value"
                sortKey="dvorp"
                active={sortKey}
                onClick={setSortKey}
              />
              <SortableHeader
                label="Util"
                sortKey="utility"
                active={sortKey}
                onClick={setSortKey}
              />
            </tr>
          </thead>
          <tbody>
            {filtered.map((player) => (
              <Row key={player.playerId} player={player} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table row + header helpers
// ---------------------------------------------------------------------------

interface SortableHeaderProps {
  label: string;
  sortKey: SortKey;
  active: SortKey;
  onClick: (key: SortKey) => void;
}

function SortableHeader({
  label,
  sortKey,
  active,
  onClick,
}: SortableHeaderProps) {
  return (
    <th className="px-3 py-2">
      <button
        type="button"
        onClick={() => onClick(sortKey)}
        className={`inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
          active === sortKey ? "text-emerald-300" : "text-slate-500 hover:text-slate-300"
        }`}
      >
        {label}
        {active === sortKey && <span className="text-emerald-400">↓</span>}
      </button>
    </th>
  );
}

interface RowProps {
  player: Player;
}

function Row({ player }: RowProps) {
  return (
    <tr className="border-b border-white/5 transition-colors hover:bg-white/5">
      <td className="px-3 py-2">
        <div className="font-medium text-white">{player.name}</div>
        <div className="text-xs text-slate-500">{player.team}</div>
      </td>
      <td className="px-3 py-2">
        <span
          className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-semibold ${POSITION_BG[player.position]}`}
        >
          {player.position}
        </span>
      </td>
      <td className="px-3 py-2 text-slate-300">
        {formatNumber(player.xfp)}
      </td>
      <td className="px-3 py-2 text-slate-300">
        {player.wopr !== null && player.wopr !== undefined
          ? player.wopr.toFixed(3)
          : "—"}
      </td>
      <td className="px-3 py-2 text-slate-300">
        {player.adp !== null && player.adp !== undefined
          ? Math.round(player.adp)
          : "—"}
      </td>
      <td className="px-3 py-2 text-slate-300">
        {formatNumber(player.replacementValue)}
      </td>
      <td className="px-3 py-2 font-semibold text-emerald-300">
        {formatUtility(player.utility)}
      </td>
    </tr>
  );
}

function sortValue(player: Player, key: SortKey): number {
  switch (key) {
    case "utility":
      return player.utility;
    case "dvorp":
      return player.dvorp;
    case "adp":
      // Lower ADP is better; invert so a higher value sorts first.
      return player.adp !== null && player.adp !== undefined ? -player.adp : Number.NEGATIVE_INFINITY;
    case "xfp":
      return player.xfp ?? Number.NEGATIVE_INFINITY;
    case "wopr":
      return player.wopr ?? Number.NEGATIVE_INFINITY;
  }
}