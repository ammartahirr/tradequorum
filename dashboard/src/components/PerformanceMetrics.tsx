import { useTheme } from '../context/ThemeContext';
import type { PerformanceMetrics as PerformanceMetricsType } from '../types/trading';
import { cardStyle, sectionTitle, statBox, labelStyle, emptyState, fontSize, spacing } from '../styles/shared';

interface PerformanceMetricsProps {
  metrics: PerformanceMetricsType | null;
}

export function PerformanceMetrics({ metrics }: PerformanceMetricsProps) {
  const { colors } = useTheme();

  if (!metrics) {
    return (
      <div style={cardStyle(colors)}>
        <h2 style={{ ...sectionTitle(colors), marginBottom: spacing.lg }}>Performance Metrics</h2>
        <div style={emptyState(colors)}>No performance data available</div>
      </div>
    );
  }

  const winRateColor = metrics.winRate >= 0.6 ? colors.success : metrics.winRate >= 0.45 ? colors.warning : colors.error;
  const rrColor = metrics.avgRiskReward >= 2 ? colors.success : metrics.avgRiskReward >= 1.5 ? colors.warning : colors.error;
  const drawdownColor = metrics.maxDrawdown <= 0.1 ? colors.success : metrics.maxDrawdown <= 0.2 ? colors.warning : colors.error;
  const sharpeColor = metrics.sharpeRatio >= 1.5 ? colors.success : metrics.sharpeRatio >= 1 ? colors.warning : colors.error;

  const losingTrades = metrics.totalTrades - metrics.winningTrades;
  const profitFactor = losingTrades > 0 ? (metrics.winningTrades * metrics.avgRiskReward) / losingTrades : metrics.winningTrades > 0 ? Infinity : 0;

  return (
    <div style={cardStyle(colors)}>
      <h2 style={{ ...sectionTitle(colors), marginBottom: spacing.xl }}>Performance Metrics</h2>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: spacing.lg }} role="list" aria-label="Performance metrics">
        <MetricCard label="Total Trades" value={metrics.totalTrades.toString()} subLabel="All Time" color={colors.textPrimary} colors={colors} highlight />
        <MetricCard label="Winners" value={metrics.winningTrades.toString()} subLabel={`${losingTrades} Losers`} color={colors.success} colors={colors} />
        <MetricCard label="Win Rate" value={`${(metrics.winRate * 100).toFixed(1)}%`} subLabel={metrics.winRate >= 0.5 ? 'Above 50%' : 'Below 50%'} color={winRateColor} colors={colors} />
        <MetricCard label="Avg R:R" value={metrics.avgRiskReward.toFixed(2)} subLabel="Risk/Reward" color={rrColor} colors={colors} />
        <MetricCard label="Max DD" value={`${(metrics.maxDrawdown * 100).toFixed(1)}%`} subLabel="Drawdown" color={drawdownColor} colors={colors} />
        <MetricCard label="Sharpe" value={metrics.sharpeRatio.toFixed(2)} subLabel="Ratio" color={sharpeColor} colors={colors} />
        <MetricCard label="Profit Factor" value={profitFactor === Infinity ? '∞' : profitFactor.toFixed(2)} subLabel="W×RR / L" color={profitFactor >= 1.5 ? colors.success : colors.warning} colors={colors} />
      </div>
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: string;
  subLabel?: string;
  color: string;
  highlight?: boolean;
  colors: ReturnType<typeof useTheme>['colors'];
}

function MetricCard({ label, value, subLabel, color, highlight, colors }: MetricCardProps) {
  return (
    <div style={{ ...statBox(colors, highlight), padding: '20px 16px' }}>
      <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>{label}</div>
      <div style={{ fontSize: fontSize.h2, fontWeight: 800, fontFamily: 'var(--font-mono)', color, letterSpacing: '-0.02em', marginBottom: spacing.sm }}>{value}</div>
      {subLabel && <div style={{ fontSize: fontSize.xs, color: colors.textMuted, fontWeight: 600, textTransform: 'uppercase' }}>{subLabel}</div>}
    </div>
  );
}
