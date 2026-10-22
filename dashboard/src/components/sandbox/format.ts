export const money = (v: number) =>
  `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
export const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : `${v.toFixed(digits)}%`;
export const num = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toFixed(digits);
export const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export type Tone = 'good' | 'bad' | 'neutral';
export const toneOf = (v: number, goodAbove = 0): Tone => (v > goodAbove ? 'good' : v < goodAbove ? 'bad' : 'neutral');

export const REGIME_COLORS: Record<string, string> = {
  trend_up: 'rgba(34,197,94,0.10)',
  trend_down: 'rgba(239,68,68,0.10)',
  range: 'rgba(59,130,246,0.09)',
  transition: 'rgba(0,0,0,0)',
  crisis: 'rgba(234,179,8,0.16)',
};
