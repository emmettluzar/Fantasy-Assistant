/**
 * Shared presentation helpers for the Fantasy Draft Assistant UI.
 *
 * Keeps position color mapping and numeric formatting in one place so the
 * draft board, recommendation card, and player list render consistently.
 */

import { Position } from "../types/protocol";

/** Tailwind text color class per position. */
export const POSITION_TEXT: Record<Position, string> = {
  QB: "text-sky-400",
  RB: "text-emerald-400",
  WR: "text-amber-400",
  TE: "text-fuchsia-400",
  K: "text-slate-400",
  DST: "text-slate-400",
};

/** Tailwind background color class per position (for badges / chips). */
export const POSITION_BG: Record<Position, string> = {
  QB: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  RB: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  WR: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  TE: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30",
  K: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  DST: "bg-slate-500/15 text-slate-300 border-slate-500/30",
};

/** Solid accent color used for the draft board cell fill. */
export const POSITION_CELL: Record<Position, string> = {
  QB: "bg-sky-500/80",
  RB: "bg-emerald-500/80",
  WR: "bg-amber-500/80",
  TE: "bg-fuchsia-500/80",
  K: "bg-slate-500/80",
  DST: "bg-slate-500/80",
};

/** Format a number to one decimal place, or "—" when null/undefined. */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(1);
}

/** Format a probability (0..1) as a whole percentage. */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Format a utility score to two decimals. */
export function formatUtility(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}