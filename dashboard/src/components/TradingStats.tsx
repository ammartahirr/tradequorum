import { useTheme } from '../context/ThemeContext';
import type { TradeRecord, PerformanceMetrics } from '../types/trading';
import { PositionStatus } from '../types/trading';
import { cardStyle, sectionTitle, statBox, labelStyle, fontSize, spacing, radius } from '../styles/shared';

interface TradingStatsProps {
  trades: TradeRecord[];
  metrics: PerformanceMetrics | null;
}

export function TradingStats({ trades }: TradingStatsProps) {
  const { colors } = useTheme();

  const closedTrades = trades.filter(t => t.status !== PositionStatus.OPEN);
  const wins = closedTrades.filter(t => t.status === PositionStatus.CLOSED_PROFIT || t.status === PositionStatus.CLOSED_TP);
  const losses = closedTrades.filter(t => t.status === PositionStatus.CLOSED_LOSS || t.status === PositionStatus.CLOSED_SL);
  
  const totalProfit = wins.reduce((sum, t) => sum + (t.pnl || 0), 0);
  const totalLoss = Math.abs(losses.reduce((sum, t) => sum + (t.pnl || 0), 0));
  const netPnL = totalProfit - totalLoss;
  
  const avgWin = wins.length > 0 ? totalProfit / wins.length : 0;
  const avgLoss = losses.length > 0 ? totalLoss / losses.length : 0;
  const profitFactor = totalLoss > 0 ? totalProfit / totalLoss : totalProfit > 0 ? Infinity : 0;
  
  const largestWin = wins.length > 0 ? Math.max(...wins.map(t => t.pnl || 0)) : 0;
  const largestLoss = losses.length > 0 ? Math.min(...losses.map(t => t.pnl || 0)) : 0;
  
  let currentStreak = 0;
  let maxWinStreak = 0;
  let maxLossStreak = 0;
  let tempWinStreak = 0;
  let tempLossStreak = 0;
  
  closedTrades.forEach(trade => {
    const isWin = trade.status === PositionStatus.CLOSED_PROFIT || trade.status === PositionStatus.CLOSED_TP;
    if (isWin) { tempWinStreak++; tempLossStreak = 0; maxWinStreak = Math.max(maxWinStreak, tempWinStreak); }
    else { tempLossStreak++; tempWinStreak = 0; maxLossStreak = Math.max(maxLossStreak, tempLossStreak); }
  });
  
  for (let i = closedTrades.length - 1; i >= 0; i--) {
    const isWin = closedTrades[i].status === PositionStatus.CLOSED_PROFIT || closedTrades[i].status === PositionStatus.CLOSED_TP;
    if (i === closedTrades.length - 1) { currentStreak = isWin ? 1 : -1; }
    else {
      const prevWin = closedTrades[i + 1].status === PositionStatus.CLOSED_PROFIT || closedTrades[i + 1].status === PositionStatus.CLOSED_TP;
      if (isWin === prevWin) currentStreak = isWin ? currentStreak + 1 : currentStreak - 1;
      else break;
    }
  }

  return (
    <div style={cardStyle(colors)}>
      <h3 style={{ ...sectionTitle(colors), marginBottom: spacing.xl }}>Detailed Trading Statistics</h3>

      <div style={{ textAlign: 'center', padding: spacing.xl, backgroundColor: colors.bgTertiary, borderRadius: radius.md, marginBottom: spacing.lg, border: `2px solid ${netPnL >= 0 ? colors.success : colors.error}` }}>
        <div style={{ fontSize: fontSize.sm, color: colors.textMuted, fontWeight: 600, marginBottom: spacing.sm, textTransform: 'uppercase' }}>Net Profit/Loss</div>
        <div style={{ fontSize: fontSize.h1, fontWeight: 800, fontFamily: 'var(--font-mono)', color: netPnL >= 0 ? colors.success : colors.error }}>{netPnL >= 0 ? '+' : ''}{netPnL.toFixed(2)}</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: spacing.sm, marginBottom: spacing.lg }}>
        <StatBox label="Total Profit" value={`+${totalProfit.toFixed(2)}`} color={colors.success} colors={colors} />
        <StatBox label="Total Loss" value={`-${totalLoss.toFixed(2)}`} color={colors.error} colors={colors} />
        <StatBox label="Avg Win" value={`+${avgWin.toFixed(2)}`} color={colors.success} colors={colors} />
        <StatBox label="Avg Loss" value={`-${avgLoss.toFixed(2)}`} color={colors.error} colors={colors} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: spacing.sm, marginBottom: spacing.lg }}>
        <StatBox label="Profit Factor" value={profitFactor === Infinity ? '∞' : profitFactor.toFixed(2)} color={profitFactor >= 1.5 ? colors.success : colors.warning} colors={colors} />
        <StatBox label="Largest Win" value={`+${largestWin.toFixed(2)}`} color={colors.success} colors={colors} />
        <StatBox label="Largest Loss" value={largestLoss.toFixed(2)} color={colors.error} colors={colors} />
        <StatBox label="Current Streak" value={`${currentStreak > 0 ? '+' : ''}${currentStreak}`} color={currentStreak > 0 ? colors.success : currentStreak < 0 ? colors.error : colors.textMuted} colors={colors} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: spacing.sm }}>
        <StatBox label="Max Win Streak" value={maxWinStreak.toString()} color={colors.success} colors={colors} />
        <StatBox label="Max Loss Streak" value={maxLossStreak.toString()} color={colors.error} colors={colors} />
      </div>
    </div>
  );
}

interface StatBoxProps {
  label: string;
  value: string;
  color: string;
  colors: ReturnType<typeof useTheme>['colors'];
}

function StatBox({ label, value, color, colors }: StatBoxProps) {
  return (
    <div style={{ ...statBox(colors), padding: spacing.md }}>
      <div style={{ ...labelStyle(colors), marginBottom: spacing.sm, fontSize: '9px' }}>{label}</div>
      <div style={{ fontSize: fontSize.xxl, fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>{value}</div>
    </div>
  );
}
