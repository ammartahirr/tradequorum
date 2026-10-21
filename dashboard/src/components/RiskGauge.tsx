import { useTheme } from '../context/ThemeContext';
import type { PerformanceMetrics } from '../types/trading';
import { cardStyle, sectionTitle, innerCard, labelStyle, progressBar, fontSize, spacing, radius } from '../styles/shared';

interface RiskGaugeProps {
  metrics: PerformanceMetrics | null;
}

export function RiskGauge({ metrics }: RiskGaugeProps) {
  const { colors } = useTheme();

  const drawdown = metrics?.maxDrawdown ?? 0;
  const sharpe = metrics?.sharpeRatio ?? 0;
  const avgRR = metrics?.avgRiskReward ?? 0;

  const riskLevel = drawdown <= 0.05 ? 'LOW' : drawdown <= 0.15 ? 'MODERATE' : drawdown <= 0.25 ? 'HIGH' : 'CRITICAL';
  const riskColor = drawdown <= 0.05 ? colors.success : drawdown <= 0.15 ? colors.warning : colors.error;
  const riskPct = Math.min(drawdown * 100 / 30, 100);

  const sharpeRating = sharpe >= 2 ? 'Excellent' : sharpe >= 1.5 ? 'Very Good' : sharpe >= 1 ? 'Good' : sharpe >= 0.5 ? 'Acceptable' : sharpe >= 0 ? 'Poor' : 'Negative';
  const sharpeColor = sharpe >= 1.5 ? colors.success : sharpe >= 1 ? colors.successLight : sharpe >= 0 ? colors.warning : colors.error;

  return (
    <div style={{ ...cardStyle(colors), height: '100%', display: 'flex', flexDirection: 'column' }}>
      <h2 style={sectionTitle(colors)}>Risk Assessment</h2>

      <div style={{ textAlign: 'center', marginBottom: spacing.xl }}>
        <div style={{ display: 'inline-block', padding: `${spacing.md} ${spacing.xxl}`, backgroundColor: riskColor + '20', border: `2px solid ${riskColor}`, borderRadius: '24px', color: riskColor, fontSize: fontSize.xxl, fontWeight: 800, fontFamily: 'var(--font-mono)', letterSpacing: '0.15em' }}>
          {riskLevel} RISK
        </div>
      </div>

      <div style={{ ...innerCard(colors), marginBottom: spacing.xl }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.md }}>
          <span style={labelStyle(colors)}>Maximum Drawdown</span>
          <span style={{ fontSize: fontSize.h3, fontWeight: 800, fontFamily: 'var(--font-mono)', color: riskColor }}>{(drawdown * 100).toFixed(1)}%</span>
        </div>
        <div style={{ ...progressBar(colors), height: '10px', border: `1px solid ${colors.border}` }}>
          <div style={{ height: '100%', width: `${riskPct}%`, backgroundColor: riskColor, borderRadius: radius.sm, transition: 'width 500ms ease' }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: spacing.sm, fontSize: fontSize.xs, color: colors.textMuted, fontFamily: 'var(--font-mono)' }}>
          <span>0%</span><span>10%</span><span>20%</span><span>30%</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: spacing.md, marginTop: 'auto' }}>
        <StatCard label="Sharpe Ratio" value={sharpe.toFixed(2)} subLabel={sharpeRating} color={sharpeColor} colors={colors} />
        <StatCard label="Avg Risk/Reward" value={avgRR.toFixed(2)} subLabel={avgRR >= 2 ? 'Excellent' : avgRR >= 1.5 ? 'Good' : 'Below Target'} color={avgRR >= 2 ? colors.success : avgRR >= 1.5 ? colors.warning : colors.error} colors={colors} />
      </div>
    </div>
  );
}

function StatCard({ label, value, subLabel, color, colors }: { label: string; value: string; subLabel: string; color: string; colors: ReturnType<typeof useTheme>['colors'] }) {
  return (
    <div style={{ ...innerCard(colors), textAlign: 'center' }}>
      <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>{label}</div>
      <div style={{ fontSize: fontSize.h2, fontWeight: 800, fontFamily: 'var(--font-mono)', color, marginBottom: spacing.xs }}>{value}</div>
      <div style={{ fontSize: fontSize.xs, color: colors.textMuted, fontWeight: 600, textTransform: 'uppercase' }}>{subLabel}</div>
    </div>
  );
}