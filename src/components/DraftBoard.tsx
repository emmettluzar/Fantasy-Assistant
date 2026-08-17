import { useMemo } from "react";
import { Users } from "lucide-react";

import { useDraftStore, DraftPickRow } from "../store/useDraftStore";
import { Position } from "../types/protocol";
import { POSITION_CELL, POSITION_TEXT } from "../lib/format";

const POSITIONS: Position[] = ["QB", "RB", "WR", "TE", "K", "DST"];

/**
 * Responsive, color-coded draft grid.
 *
 * Each column is a drafting team; each row is a round. Picks are mapped into
 * the grid using a 0-based team index and a 1-based round. Snake drafts are
 * correctly placed by the backend (which produces explicit round + team_index
 * per pick), so this grid is a pure visual projection.
 */
export default function DraftBoard() {
  const picks = useDraftStore((s) => s.picks);
  const teams = useDraftStore((s) => s.teams);
  const userTeamIndex = useDraftStore((s) => s.userTeamIndex);

  const rounds = useMemo(() => {
    if (picks.length === 0) return 1;
    return Math.max(1, ...picks.map((p) => p.round));
  }, [picks]);

  // Map team+round -> pick for O(1) cell lookup.
  const grid = useMemo(() => {
    const map = new Map<string, DraftPickRow>();
    for (const pick of picks) {
      map.set(`${pick.teamIndex}:${pick.round}`, pick);
    }
    return map;
  }, [picks]);

  if (teams.length === 0) {
    return (
      <div className="flex h-full min-h-[320px] flex-col items-center justify-center rounded-2xl border border-white/10 bg-slate-900/50 p-6 text-center">
        <Users className="h-10 w-10 text-slate-600" />
        <p className="mt-3 text-sm text-slate-400">
          Configure a league to populate the draft board.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-white/10 bg-slate-900/50">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-white/10">
            <th className="sticky left-0 z-10 bg-slate-900 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
              Rd
            </th>
            {teams.map((team) => {
              const isUser = team.index === userTeamIndex;
              return (
                <th
                  key={team.index}
                  className={`px-2 py-2 text-center text-xs font-semibold ${
                    isUser
                      ? "bg-emerald-500/10 text-emerald-300"
                      : "text-slate-400"
                  }`}
                >
                  <span className="block truncate">{team.name}</span>
                  {isUser && (
                    <span className="text-[10px] font-medium text-emerald-400/70">
                      You
                    </span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rounds }, (_, roundIndex) => {
            const round = roundIndex + 1;
            return (
              <tr key={round} className="border-b border-white/5">
                <td className="sticky left-0 z-10 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-500">
                  {round}
                </td>
                {teams.map((team) => {
                  const pick = grid.get(`${team.index}:${round}`);
                  return (
                    <td
                      key={team.index}
                      className="h-12 min-w-[96px] px-1.5 py-1 text-center align-middle"
                    >
                      {pick ? (
                        <Cell pick={pick} />
                      ) : (
                        <span className="block h-full w-full rounded-md border border-dashed border-white/5" />
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* Position color legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-white/10 px-3 py-3">
        {POSITIONS.map((position) => (
          <span
            key={position}
            className={`flex items-center gap-1.5 text-xs font-medium ${POSITION_TEXT[position]}`}
          >
            <span
              className={`h-2 w-2 rounded-full ${POSITION_CELL[position]}`}
            />
            {position}
          </span>
        ))}
      </div>
    </div>
  );
}

function Cell({ pick }: { pick: DraftPickRow }) {
  return (
    <div
      className={`flex h-full w-full flex-col items-center justify-center rounded-md px-1 text-white shadow-sm ${POSITION_CELL[pick.position]}`}
      title={`${pick.playerName} (${pick.position})`}
    >
      <span className="truncate text-xs font-semibold leading-tight">
        {pick.playerName}
      </span>
      <span className="text-[10px] leading-tight opacity-80">
        {pick.position}
      </span>
    </div>
  );
}