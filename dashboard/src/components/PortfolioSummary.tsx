import { useTheme } from '../context/ThemeContext';
import type { Position, PerformanceMetrics } from '../types/trading';
import { PositionStatus } from '../types/trading';
import { cardStyle, sectionTitle, statBox, labelStyle, fontSize, spacing, radius } from '../styles/shared';

interface PortfolioSummaryProps {
  positions: Position[];
  metrics: PerformanceMetrics | null;
}

export function PortfolioSummary({ positions, metrics }: PortfolioSummaryProps) {
  const { colors } = useTheme();

  const openPositions = positions.filter((p) => p.status === PositionStatus.OPEN);
  const totalPnL = openPositions.reduce((sum, p) => sum + (p.pnl ?? 0), 0);
  const totalPnLPct = openPositions.length > 0
    ? openPositions.reduce((sum, p) => sum + (p.pnlPct ?? 0), 0) / openPositions.length
    : 0;

  const profitableCount = openPositions.filter((p) => (p.pnl ?? 0) > 0).length;
  const losingCount = openPositions.filter((p) => (p.pnl ?? 0) < 0).length;
  const breakEvenCount = openPositions.filter((p) => (p.pnl ?? 0) === 0).length;
  const totalExposure = openPositions.reduce((sum, p) => sum + (p.positionSize * p.entryPrice), 0);
  const avgEntry = openPositions.length > 0
    ? openPositions.reduce((sum, p) => sum + p.entryPrice, 0) / openPositions.length
    : 0;

  return (
    <div style={cardStyle(colors)}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: spacing.xxl }}>
        <div>
          <h2 style={{ ...sectionTitle(colors), marginBottom: spacing.lg }}>Portfolio Overview</h2>
          <span style={{ ...labelStyle(colors), display: 'block', marginBottom: spacing.sm }}>Unrealized P&L</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.xl, marginTop: spacing.md }}>
            <span style={{
              fontSize: '42px',
              fontWeight: 800,
              fontFamily: 'var(--font-mono)',
              color: totalPnL >= 0 ? colors.success : colors.error,
              letterSpacing: '-0.03em',
              lineHeight: 1,
            }}>
              {totalPnL >= 0 ? '+' : ''}{totalPnL.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <span style={{
              fontSize: fontSize.sm,
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              color: totalPnLPct >= 0 ? colors.success : colors.error,
              padding: '4px 8px',
              backgroundColor: totalPnLPct >= 0 ? colors.successBg : colors.errorBg,
              borderRadius: radius.sm,
              border: `1px solid ${totalPnLPct >= 0 ? colors.success : colors.error}`,
            }}>
              {totalPnLPct >= 0 ? '+' : ''}{totalPnLPct.toFixed(2)}%
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '32px' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>Open Positions</div>
            <div style={{ fontSize: fontSize.h1, fontWeight: 800, fontFamily: 'var(--font-mono)', color: colors.textPrimary }}>
              {openPositions.length}
            </div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>Total Exposure</div>
            <div style={{ fontSize: fontSize.h1, fontWeight: 800, fontFamily: 'var(--font-mono)', color: colors.textPrimary }}>
              ${totalExposure >= 1000 ? (totalExposure / 1000).toFixed(1) + 'K' : totalExposure.toFixed(0)}
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: spacing.md }}>
        <StatBox label="Profitable" value={profitableCount.toString()} color={colors.success} bgColor={colors.successBg} borderColor={colors.success} colors={colors} />
        <StatBox label="Losing" value={losingCount.toString()} color={colors.error} bgColor={colors.errorBg} borderColor={colors.error} colors={colors} />
        <StatBox label="Break Even" value={breakEvenCount.toString()} color={colors.textPrimary} colors={colors} />
        <StatBox label="Win Rate" value={metrics ? `${(metrics.winRate * 100).toFixed(0)}%` : '-'} color={colors.textPrimary} colors={colors} highlight />
        <StatBox label="Total Trades" value={metrics?.totalTrades.toString() ?? '-'} color={colors.textPrimary} colors={colors} />
        <StatBox label="Avg Entry" value={avgEntry > 0 ? `${avgEntry.toFixed(2)}` : '-'} color={colors.textPrimary} colors={colors} />
      </div>
    </div>
  );
}

interface StatBoxProps {
  label: string;
  value: string;
  color: string;
  bgColor?: string;
  borderColor?: string;
  highlight?: boolean;
  colors: ReturnType<typeof useTheme>['colors'];
}

function StatBox({ label, value, color, bgColor, borderColor, highlight, colors }: StatBoxProps) {
  return (
    <div style={{
      ...statBox(colors, highlight),
      backgroundColor: bgColor || colors.bgTertiary,
      border: borderColor ? `1px solid ${borderColor}40` : highlight ? `2px solid ${colors.textPrimary}` : `1px solid ${colors.border}`,
    }}>
      <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>{label}</div>
      <div style={{ fontSize: fontSize.h2, fontWeight: 800, color, fontFamily: 'var(--font-mono)' }}>{value}</div>
    </div>
  );
}
