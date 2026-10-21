import { useTheme } from '../context/ThemeContext';
import type { Position } from '../types/trading';
import { PositionStatus, TradeAction } from '../types/trading';
import { cardStyle, sectionTitle, emptyState, tableHeader, tableCell, badge, fontSize, spacing } from '../styles/shared';

interface PositionsTableProps {
  positions: Position[];
}

function formatPrice(price: number): string {
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPnL(pnl: number | undefined, pnlPct: number | undefined): { text: string; pctText: string; isPositive: boolean } {
  if (pnl === undefined) return { text: '-', pctText: '', isPositive: true };
  const sign = pnl >= 0 ? '+' : '';
  const pctStr = pnlPct !== undefined ? `${sign}${pnlPct.toFixed(2)}%` : '';
  return { text: `${sign}${pnl.toFixed(2)}`, pctText: pctStr, isPositive: pnl >= 0 };
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function calculateRiskPct(entry: number, sl: number, isBuy: boolean): number {
  if (isBuy) return ((entry - sl) / entry) * 100;
  return ((sl - entry) / entry) * 100;
}

export function PositionsTable({ positions }: PositionsTableProps) {
  const { colors } = useTheme();

  const openPositions = positions.filter((p) => p.status === PositionStatus.OPEN);
  const totalPnL = openPositions.reduce((sum, p) => sum + (p.pnl ?? 0), 0);

  return (
    <div style={cardStyle(colors)}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xl }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.lg }}>
          <h2 style={{ ...sectionTitle(colors), margin: 0 }}>Open Positions</h2>
          <span style={{
            padding: '6px 14px',
            backgroundColor: colors.bgTertiary,
            borderRadius: '20px',
            fontSize: fontSize.xl,
            fontWeight: 800,
            fontFamily: 'var(--font-mono)',
            color: colors.textPrimary,
            border: `1px solid ${colors.border}`,
          }}>
            {openPositions.length}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
          <span style={{ fontSize: fontSize.md, color: colors.textMuted, fontWeight: 600 }}>Total P&L:</span>
          <span style={{ fontSize: fontSize.xxl, fontWeight: 800, fontFamily: 'var(--font-mono)', color: totalPnL >= 0 ? colors.success : colors.error }}>
            {totalPnL >= 0 ? '+' : ''}{totalPnL.toFixed(2)}
          </span>
        </div>
      </div>

      {openPositions.length === 0 ? (
        <div style={emptyState(colors)}>
          <div style={{ fontSize: '32px', marginBottom: spacing.md }}>📭</div>
          <div style={{ fontSize: fontSize.xl, fontWeight: 600 }}>No open positions</div>
          <div style={{ fontSize: fontSize.md, marginTop: spacing.xs }}>Waiting for trade signals...</div>
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: fontSize.lg }} role="table" aria-label="Open positions">
            <thead>
              <tr style={{ borderBottom: `2px solid ${colors.border}` }}>
                <th style={tableHeader(colors)}>Symbol</th>
                <th style={tableHeader(colors)}>Side</th>
                <th style={{ ...tableHeader(colors), textAlign: 'right' }}>Entry Price</th>
                <th style={{ ...tableHeader(colors), textAlign: 'right' }}>Stop Loss</th>
                <th style={{ ...tableHeader(colors), textAlign: 'right' }}>Take Profit</th>
                <th style={{ ...tableHeader(colors), textAlign: 'right' }}>Size</th>
                <th style={{ ...tableHeader(colors), textAlign: 'right' }}>Risk %</th>
                <th style={{ ...tableHeader(colors), textAlign: 'right' }}>P&L</th>
                <th style={{ ...tableHeader(colors), textAlign: 'right' }}>Opened</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.map((position, idx) => {
                const isBuy = position.action === TradeAction.STRONG_BUY || position.action === TradeAction.BUY;
                const pnlData = formatPnL(position.pnl, position.pnlPct);
                const riskPct = calculateRiskPct(position.entryPrice, position.stopLoss, isBuy);

                return (
                  <tr key={position.tradeId} style={{ borderBottom: `1px solid ${colors.border}`, backgroundColor: idx % 2 === 0 ? 'transparent' : colors.bgTertiary }}>
                    <td style={tableCell(colors)}>
                      <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: fontSize.xl }}>{position.symbol}</span>
                    </td>
                    <td style={tableCell(colors)}>
                      <span style={badge(isBuy ? colors.success : colors.error, isBuy ? colors.successBg : colors.errorBg)}>
                        {isBuy ? 'LONG' : 'SHORT'}
                      </span>
                    </td>
                    <td style={{ ...tableCell(colors), textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>${formatPrice(position.entryPrice)}</td>
                    <td style={{ ...tableCell(colors), textAlign: 'right', fontFamily: 'var(--font-mono)', color: colors.error, fontWeight: 600 }}>${formatPrice(position.stopLoss)}</td>
                    <td style={{ ...tableCell(colors), textAlign: 'right', fontFamily: 'var(--font-mono)', color: colors.success, fontWeight: 600 }}>${formatPrice(position.takeProfit)}</td>
                    <td style={{ ...tableCell(colors), textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{position.positionSize.toFixed(4)}</td>
                    <td style={{ ...tableCell(colors), textAlign: 'right', fontFamily: 'var(--font-mono)', color: colors.warning, fontWeight: 600 }}>{riskPct.toFixed(2)}%</td>
                    <td style={{ ...tableCell(colors), textAlign: 'right' }}>
                      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: pnlData.isPositive ? colors.success : colors.error }}>{pnlData.text}</div>
                      <div style={{ fontSize: fontSize.xs, color: pnlData.isPositive ? colors.success : colors.error }}>{pnlData.pctText}</div>
                    </td>
                    <td style={{ ...tableCell(colors), textAlign: 'right', color: colors.textSecondary, fontSize: fontSize.md }}>{formatDate(position.openedAt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
