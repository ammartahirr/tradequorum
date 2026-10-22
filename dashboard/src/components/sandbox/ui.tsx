import type { CSSProperties, ReactNode } from 'react';
import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, ComposedChart } from 'recharts';
import { useTheme } from '../../context/ThemeContext';
import { cardStyle, fontSize, labelStyle, sectionTitle, spacing } from '../../styles/shared';
import type { Tone } from './format';

export function Stat({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: Tone; hint?: string }) {
  const { colors } = useTheme();
  const color = tone === 'good' ? colors.success : tone === 'bad' ? colors.error : colors.textPrimary;
  return (
    <div style={{ ...cardStyle(colors), padding: spacing.lg }} title={hint}>
      <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>{label}</div>
      <div style={{ fontSize: fontSize.h3, fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>{value}</div>
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: spacing.lg,
        marginBottom: spacing.xxl,
      }}
    >
      {children}
    </div>
  );
}

export function Card({ title, children, style }: { title: string; children: ReactNode; style?: CSSProperties }) {
  const { colors } = useTheme();
  return (
    <section style={{ ...cardStyle(colors), minWidth: 0, ...style }}>
      <h2 style={{ ...sectionTitle(colors), marginBottom: spacing.md }}>{title}</h2>
      {children}
    </section>
  );
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  const { colors } = useTheme();
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: fontSize.lg, color: colors.textSecondary, lineHeight: 1.9 }}>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: spacing.lg }}>
          <span style={{ color: colors.textMuted }}>{k}</span>
          <span style={{ color: colors.textPrimary }}>{v}</span>
        </div>
      ))}
    </div>
  );
}

export function EquityChart({
  data,
  compare,
  compareLabel,
  positive,
}: {
  data: { time: number; equity: number }[];
  compare?: { time: number; equity: number }[];
  compareLabel?: string;
  positive: boolean;
}) {
  const { colors } = useTheme();
  const merged = data.map((p, i) => ({
    t: new Date(p.time * 1000).toLocaleDateString(),
    equity: Math.round(p.equity),
    compare: compare && compare[i] ? Math.round(compare[i].equity) : undefined,
  }));
  const stroke = positive ? colors.success : colors.error;
  if (!compare || compare.length === 0) {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={merged}>
          <CartesianGrid stroke={colors.border} strokeDasharray="3 3" />
          <XAxis dataKey="t" stroke={colors.textMuted} fontSize={11} minTickGap={40} />
          <YAxis stroke={colors.textMuted} fontSize={11} domain={['auto', 'auto']} width={80} />
          <Tooltip contentStyle={{ backgroundColor: colors.bgSecondary, border: `1px solid ${colors.border}` }} />
          <Area type="monotone" dataKey="equity" stroke={stroke} fill={positive ? colors.successBg : colors.errorBg} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    );
  }
  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: fontSize.md, color: colors.textMuted, marginBottom: spacing.xs }}>
        <span style={{ color: stroke }}>━ selected</span>
        <span style={{ marginLeft: spacing.lg }}>┅ {compareLabel ?? 'comparison'}</span>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={merged}>
        <CartesianGrid stroke={colors.border} strokeDasharray="3 3" />
        <XAxis dataKey="t" stroke={colors.textMuted} fontSize={11} minTickGap={40} />
        <YAxis stroke={colors.textMuted} fontSize={11} domain={['auto', 'auto']} width={80} />
        <Tooltip contentStyle={{ backgroundColor: colors.bgSecondary, border: `1px solid ${colors.border}` }} />
        <Area name="selected" type="monotone" dataKey="equity" stroke={stroke} fill={positive ? colors.successBg : colors.errorBg} dot={false} isAnimationActive={false} />
        <Line name={compareLabel ?? 'comparison'} type="monotone" dataKey="compare" stroke={colors.textMuted} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
      </div>
    </div>
  );
}

export function TradeTable<T>({
  rows,
  columns,
  selected,
  onSelect,
  rowTitle,
}: {
  rows: T[];
  columns: { header: string; cell: (r: T, i: number) => ReactNode; color?: (r: T) => string | undefined }[];
  selected: number | null;
  onSelect: (i: number | null) => void;
  rowTitle?: (r: T) => string;
}) {
  const { colors } = useTheme();
  return (
    <div style={{ overflowX: 'auto', maxHeight: 520, overflowY: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: fontSize.lg }}>
        <thead style={{ position: 'sticky', top: 0, backgroundColor: colors.bgSecondary }}>
          <tr style={{ textAlign: 'left' }}>
            {columns.map((c) => (
              <th key={c.header} style={{ padding: spacing.sm, borderBottom: `1px solid ${colors.border}`, ...labelStyle(colors) }}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              onClick={() => onSelect(selected === i ? null : i)}
              title={rowTitle?.(r)}
              style={{ cursor: 'pointer', backgroundColor: selected === i ? colors.bgHover : 'transparent', color: colors.textPrimary }}
            >
              {columns.map((c) => (
                <td key={c.header} style={{ padding: spacing.sm, color: c.color?.(r) }}>
                  {c.cell(r, i)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
