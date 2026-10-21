import { useTheme } from '../context/ThemeContext';
import type { TradeRecord } from '../types/trading';
import { PositionStatus, TradeAction } from '../types/trading';
import { cardStyle, sectionTitle, emptyState, badge, fontSize, spacing, radius } from '../styles/shared';

interface TradeHistoryProps {
  trades: TradeRecord[];
  limit?: number;
}

function formatPrice(price: number): string {
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPnL(pnl: number | undefined): { text: string; isPositive: boolean } {
  if (pnl === undefined) return { text: '-', isPositive: true };
  const sign = pnl >= 0 ? '+' : '';
  return { text: `${sign}${pnl.toFixed(2)}`, isPositive: pnl >= 0 };
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const statusConfig: Record<PositionStatus, { label: string; short: string }> = {
  [PositionStatus.OPEN]: { label: 'Open', short: 'OPEN' },
  [PositionStatus.CLOSED_PROFIT]: { label: 'Profit', short: 'WIN' },
  [PositionStatus.CLOSED_LOSS]: { label: 'Loss', short: 'LOSS' },
  [PositionStatus.CLOSED_SL]: { label: 'Stop Loss Hit', short: 'SL' },
  [PositionStatus.CLOSED_TP]: { label: 'Take Profit Hit', short: 'TP' },
};

export function TradeHistory({ trades, limit = 20 }: TradeHistoryProps) {
  const { colors } = useTheme();
  const displayTrades = trades.slice(0, limit);

  const wins = trades.filter((t) => t.status === PositionStatus.CLOSED_PROFIT || t.status === PositionStatus.CLOSED_TP).length;
  const losses = trades.filter((t) => t.status === PositionStatus.CLOSED_LOSS || t.status === PositionStatus.CLOSED_SL).length;
  const totalPnL = trades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);

  return (
    <div style={{ ...cardStyle(colors), height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xl }}>
        <h2 style={{ ...sectionTitle(colors), margin: 0 }}>Trade History</h2>
        <div style={{ display: 'flex', gap: spacing.sm, alignItems: 'center' }}>
          <span style={badge(colors.success, colors.successBg)}>{wins}W</span>
          <span style={badge(colors.error, colors.errorBg)}>{losses}L</span>
          <span style={{ marginLeft: spacing.sm, fontSize: fontSize.xl, fontWeight: 700, fontFamily: 'var(--font-mono)', color: totalPnL >= 0 ? colors.success : colors.error }}>
            {totalPnL >= 0 ? '+' : ''}{totalPnL.toFixed(2)}
          </span>
        </div>
      </div>

      {displayTrades.length === 0 ? (
        <div style={{ ...emptyState(colors), flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ fontSize: '32px', marginBottom: spacing.md }}>📋</div>
          <div style={{ fontSize: fontSize.xl, fontWeight: 600 }}>No trade history</div>
          <div style={{ fontSize: fontSize.md, marginTop: spacing.xs }}>Completed trades will appear here</div>
        </div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
            {displayTrades.map((trade) => {
              const pnlData = formatPnL(trade.pnl);
              const isBuy = trade.action === TradeAction.STRONG_BUY || trade.action === TradeAction.BUY;
              const isWin = trade.status === PositionStatus.CLOSED_PROFIT || trade.status === PositionStatus.CLOSED_TP;
              const statusInfo = statusConfig[trade.status];
              const pnlPct = trade.pnlPct ?? 0;

              return (
                <div key={trade.tradeId} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: spacing.lg,
                  padding: spacing.lg,
                  backgroundColor: colors.bgTertiary,
                  borderRadius: radius.md,
                  borderLeft: `4px solid ${isWin ? colors.success : colors.error}`,
                  border: `1px solid ${colors.border}`,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm }}>
                      <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: colors.textPrimary, fontSize: fontSize.xl }}>{trade.symbol}</span>
                      <span style={badge(isBuy ? colors.success : colors.error, isBuy ? colors.successBg : colors.errorBg)}>{isBuy ? 'LONG' : 'SHORT'}</span>
                      <span style={badge(isWin ? colors.success : colors.error, isWin ? colors.successBg : colors.errorBg)}>{statusInfo.short}</span>
                    </div>
                    <div style={{ fontSize: fontSize.md, color: colors.textSecondary, fontFamily: 'var(--font-mono)' }}>
                      <span style={{ color: colors.textMuted }}>Entry:</span> ${formatPrice(trade.entryPrice)}
                      <span style={{ margin: '0 8px', color: colors.textMuted }}>→</span>
                      <span style={{ color: colors.textMuted }}>Exit:</span> {trade.exitPrice ? `${formatPrice(trade.exitPrice)}` : '-'}
                    </div>
                    <div style={{ fontSize: fontSize.xs, color: colors.textMuted, marginTop: spacing.xs }}>{trade.closedAt ? formatDate(trade.closedAt) : '-'}</div>
                  </div>

                  <div style={{ textAlign: 'right', minWidth: '80px' }}>
                    <div style={{ fontWeight: 800, fontFamily: 'var(--font-mono)', fontSize: '18px', color: pnlData.isPositive ? colors.success : colors.error, marginBottom: '2px' }}>{pnlData.text}</div>
                    <div style={{ fontSize: fontSize.sm, fontWeight: 600, fontFamily: 'var(--font-mono)', color: pnlData.isPositive ? colors.success : colors.error }}>{pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
