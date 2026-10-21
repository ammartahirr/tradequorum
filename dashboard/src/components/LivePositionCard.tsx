import { useTheme } from '../context/ThemeContext';
import type { Position } from '../types/trading';
import { PositionStatus, TradeAction, Conviction } from '../types/trading';
import { cardStyle, sectionTitle, emptyState, badge, labelStyle, fontSize, spacing, radius, progressBar } from '../styles/shared';

interface LivePositionCardProps {
  position: Position;
}

function calculateWinProbability(position: Position): number {
  let probability = 50;
  if (position.pnl && position.pnl > 0) probability += 15;
  if (position.pnl && position.pnl < 0) probability -= 10;
  if (position.conviction === Conviction.HIGH) probability += 10;
  if (position.conviction === Conviction.LOW) probability -= 5;
  
  const isBuy = position.action === TradeAction.STRONG_BUY || position.action === TradeAction.BUY;
  const distanceToTP = isBuy ? position.takeProfit - position.entryPrice : position.entryPrice - position.takeProfit;
  const currentPrice = position.entryPrice + (position.pnl || 0) / position.positionSize;
  const progressToTP = isBuy ? (currentPrice - position.entryPrice) / distanceToTP : (position.entryPrice - currentPrice) / distanceToTP;
  
  if (progressToTP > 0.5) probability += 15;
  if (progressToTP > 0.75) probability += 10;
  if (progressToTP < -0.25) probability -= 15;
  
  return Math.max(5, Math.min(95, probability));
}

function calculateTimeInTrade(openedAt: string): string {
  const opened = new Date(openedAt);
  const now = new Date();
  const diffMs = now.getTime() - opened.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffDays > 0) return `${diffDays}d ${diffHours % 24}h`;
  if (diffHours > 0) return `${diffHours}h ${diffMins % 60}m`;
  return `${diffMins}m`;
}

export function LivePositionCard({ position }: LivePositionCardProps) {
  const { colors } = useTheme();
  
  const isBuy = position.action === TradeAction.STRONG_BUY || position.action === TradeAction.BUY;
  const winProbability = calculateWinProbability(position);
  const timeInTrade = calculateTimeInTrade(position.openedAt);
  
  const pnl = position.pnl ?? 0;
  const pnlPct = position.pnlPct ?? 0;
  const isProfit = pnl >= 0;
  
  const distanceToTP = Math.abs(position.takeProfit - position.entryPrice);
  const distanceToSL = Math.abs(position.entryPrice - position.stopLoss);
  const currentMove = pnl / position.positionSize;
  const progressPct = isProfit ? Math.min(100, (currentMove / distanceToTP) * 100) : Math.min(100, (Math.abs(currentMove) / distanceToSL) * 100);
  const probColor = winProbability >= 70 ? colors.success : winProbability >= 50 ? colors.warning : colors.error;

  return (
    <div style={{ backgroundColor: colors.bgTertiary, border: `1px solid ${colors.border}`, borderRadius: radius.lg, padding: spacing.lg, borderLeft: `4px solid ${isProfit ? colors.success : colors.error}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: spacing.md }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.xs }}>
            <span style={{ fontSize: '18px', fontWeight: 800, fontFamily: 'var(--font-mono)', color: colors.textPrimary }}>{position.symbol}</span>
            <span style={badge(isBuy ? colors.success : colors.error, isBuy ? colors.successBg : colors.errorBg)}>{isBuy ? 'LONG' : 'SHORT'}</span>
          </div>
          <div style={{ fontSize: fontSize.sm, color: colors.textMuted }}>Open for {timeInTrade}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: fontSize.h3, fontWeight: 800, fontFamily: 'var(--font-mono)', color: isProfit ? colors.success : colors.error }}>{isProfit ? '+' : ''}{pnl.toFixed(2)}</div>
          <div style={{ fontSize: fontSize.md, fontFamily: 'var(--font-mono)', color: isProfit ? colors.success : colors.error }}>{isProfit ? '+' : ''}{pnlPct.toFixed(2)}%</div>
        </div>
      </div>

      <div style={{ marginBottom: spacing.md, padding: spacing.md, backgroundColor: colors.bgSecondary, borderRadius: radius.md }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm }}>
          <span style={labelStyle(colors)}>Win Probability</span>
          <span style={{ fontSize: fontSize.xxl, fontWeight: 800, fontFamily: 'var(--font-mono)', color: probColor }}>{winProbability.toFixed(0)}%</span>
        </div>
        <div style={progressBar(colors)}>
          <div style={{ height: '100%', width: `${winProbability}%`, backgroundColor: probColor, borderRadius: radius.sm, transition: 'width 300ms ease' }} />
        </div>
      </div>

      <div style={{ marginBottom: spacing.md }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm }}>
          <span style={{ fontSize: fontSize.xs, fontWeight: 700, color: colors.error }}>SL: ${position.stopLoss.toFixed(2)}</span>
          <span style={{ fontSize: fontSize.xs, fontWeight: 700, color: colors.textMuted }}>Entry: ${position.entryPrice.toFixed(2)}</span>
          <span style={{ fontSize: fontSize.xs, fontWeight: 700, color: colors.success }}>TP: ${position.takeProfit.toFixed(2)}</span>
        </div>
        <div style={{ height: '6px', backgroundColor: colors.bgSecondary, borderRadius: '3px', position: 'relative' }}>
          <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: '2px', backgroundColor: colors.textMuted, transform: 'translateX(-50%)' }} />
          <div style={{ position: 'absolute', left: isProfit ? '50%' : `${50 - progressPct / 2}%`, width: `${progressPct / 2}%`, height: '100%', backgroundColor: isProfit ? colors.success : colors.error, borderRadius: '3px', transition: 'all 300ms ease' }} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: spacing.sm }}>
        <div style={{ textAlign: 'center', padding: spacing.sm, backgroundColor: colors.bgSecondary, borderRadius: radius.md }}>
          <div style={{ fontSize: '9px', color: colors.textMuted, fontWeight: 600, marginBottom: '2px' }}>SIZE</div>
          <div style={{ fontSize: fontSize.md, fontWeight: 700, fontFamily: 'var(--font-mono)', color: colors.textPrimary }}>{position.positionSize.toFixed(2)}</div>
        </div>
        <div style={{ textAlign: 'center', padding: spacing.sm, backgroundColor: colors.bgSecondary, borderRadius: radius.md }}>
          <div style={{ fontSize: '9px', color: colors.textMuted, fontWeight: 600, marginBottom: '2px' }}>CONVICTION</div>
          <div style={{ fontSize: fontSize.md, fontWeight: 700, fontFamily: 'var(--font-mono)', color: position.conviction === Conviction.HIGH ? colors.success : position.conviction === Conviction.MEDIUM ? colors.warning : colors.textMuted }}>{position.conviction}</div>
        </div>
        <div style={{ textAlign: 'center', padding: spacing.sm, backgroundColor: colors.bgSecondary, borderRadius: radius.md }}>
          <div style={{ fontSize: '9px', color: colors.textMuted, fontWeight: 600, marginBottom: '2px' }}>R:R</div>
          <div style={{ fontSize: fontSize.md, fontWeight: 700, fontFamily: 'var(--font-mono)', color: colors.textPrimary }}>{(distanceToTP / distanceToSL).toFixed(2)}</div>
        </div>
      </div>
    </div>
  );
}

interface LivePositionsGridProps {
  positions: Position[];
}

export function LivePositionsGrid({ positions }: LivePositionsGridProps) {
  const { colors } = useTheme();
  const openPositions = positions.filter(p => p.status === PositionStatus.OPEN);

  return (
    <div style={cardStyle(colors)}>
      <h3 style={{ ...sectionTitle(colors), marginBottom: spacing.lg }}>Live Positions with Win Probability</h3>
      {openPositions.length === 0 ? (
        <div style={emptyState(colors)}>No open positions</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: spacing.md }}>
          {openPositions.map(position => (<LivePositionCard key={position.tradeId} position={position} />))}
        </div>
      )}
    </div>
  );
}
