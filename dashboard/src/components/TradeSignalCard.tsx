import { useTheme } from '../context/ThemeContext';
import type { TradeSignal } from '../types/trading';
import { TradeAction, Conviction } from '../types/trading';
import { cardStyle, sectionTitle, emptyState, statBox, labelStyle, badge, fontSize, spacing, radius } from '../styles/shared';

interface TradeSignalCardProps {
  signal: TradeSignal;
}

function formatPrice(price: number): string {
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function TradeSignalCard({ signal }: TradeSignalCardProps) {
  const { colors } = useTheme();

  const isBuy = signal.action === TradeAction.STRONG_BUY || signal.action === TradeAction.BUY;
  const isSell = signal.action === TradeAction.STRONG_SELL || signal.action === TradeAction.SELL;
  const isStrong = signal.action === TradeAction.STRONG_BUY || signal.action === TradeAction.STRONG_SELL;
  const isActionable = signal.action !== TradeAction.NO_TRADE && signal.action !== TradeAction.HOLD;

  const actionColor = isBuy ? colors.success : isSell ? colors.error : colors.textMuted;
  const convictionLevel = signal.conviction === Conviction.HIGH ? 3 : signal.conviction === Conviction.MEDIUM ? 2 : 1;

  const riskAmount = Math.abs(signal.entryPrice - signal.stopLoss);
  const rewardAmount = Math.abs(signal.takeProfit - signal.entryPrice);
  const riskPct = (riskAmount / signal.entryPrice) * 100;
  const rewardPct = (rewardAmount / signal.entryPrice) * 100;

  return (
    <div style={{ backgroundColor: colors.bgTertiary, borderRadius: radius.lg, padding: spacing.xl, border: `1px solid ${colors.border}`, position: 'relative', overflow: 'hidden' }} role="article" aria-label={`Trade signal for ${signal.symbol}`}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '4px', backgroundColor: actionColor }} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: spacing.lg }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.lg }}>
          <span style={{ fontSize: '24px', fontWeight: 800, fontFamily: 'var(--font-mono)', color: colors.textPrimary }}>{signal.symbol}</span>
          <span style={{ ...badge(actionColor, actionColor + '20'), fontSize: fontSize.lg, letterSpacing: '0.05em', border: `1px solid ${actionColor}` }}>
            {isStrong ? '⚡ ' : ''}{signal.action.replace('_', ' ')}
          </span>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.xs }}>
            {[1, 2, 3].map((level) => (
              <div key={level} style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: level <= convictionLevel ? actionColor : colors.border }} />
            ))}
            <span style={{ ...labelStyle(colors), marginLeft: spacing.sm }}>{signal.conviction}</span>
          </div>
          <div style={{ fontSize: fontSize.sm, color: colors.textMuted, fontFamily: 'var(--font-mono)' }}>{formatDate(signal.timestamp)} {formatTime(signal.timestamp)}</div>
        </div>
      </div>

      {isActionable && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: spacing.md, marginBottom: spacing.lg }}>
          <PriceBox label="Entry Price" value={signal.entryPrice} color={colors.textPrimary} colors={colors} />
          <PriceBox label="Stop Loss" value={signal.stopLoss} color={colors.error} subValue={`-${riskPct.toFixed(2)}%`} colors={colors} />
          <PriceBox label="Take Profit" value={signal.takeProfit} color={colors.success} subValue={`+${rewardPct.toFixed(2)}%`} colors={colors} />
        </div>
      )}

      {isActionable && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: spacing.md, marginBottom: spacing.lg, padding: spacing.lg, backgroundColor: colors.bgSecondary, borderRadius: radius.md, border: `1px solid ${colors.border}` }}>
          <MetricItem label="R:R Ratio" value={signal.riskRewardRatio.toFixed(2)} color={signal.riskRewardRatio >= 2 ? colors.success : signal.riskRewardRatio >= 1.5 ? colors.warning : colors.error} colors={colors} />
          <MetricItem label="Position Size" value={`${(signal.positionSizePct * 100).toFixed(1)}%`} color={colors.textPrimary} colors={colors} />
          <MetricItem label="Risk Amount" value={`${riskAmount.toFixed(2)}`} color={colors.error} colors={colors} />
          <MetricItem label="Reward Amount" value={`${rewardAmount.toFixed(2)}`} color={colors.success} colors={colors} />
        </div>
      )}

      <div style={{ padding: spacing.lg, backgroundColor: colors.bgSecondary, borderRadius: radius.md, border: `1px solid ${colors.border}` }}>
        <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>Analysis & Reasoning</div>
        <p style={{ fontSize: fontSize.lg, color: colors.textSecondary, lineHeight: 1.7, margin: 0 }}>{signal.reasoning}</p>
      </div>
    </div>
  );
}

interface PriceBoxProps {
  label: string;
  value: number;
  color: string;
  subValue?: string;
  colors: ReturnType<typeof useTheme>['colors'];
}

function PriceBox({ label, value, color, subValue, colors }: PriceBoxProps) {
  return (
    <div style={statBox(colors)}>
      <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>{label}</div>
      <div style={{ fontSize: fontSize.h3, fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>${formatPrice(value)}</div>
      {subValue && <div style={{ fontSize: fontSize.sm, fontWeight: 600, fontFamily: 'var(--font-mono)', color, marginTop: spacing.xs }}>{subValue}</div>}
    </div>
  );
}

interface MetricItemProps {
  label: string;
  value: string;
  color: string;
  colors: ReturnType<typeof useTheme>['colors'];
}

function MetricItem({ label, value, color, colors }: MetricItemProps) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ ...labelStyle(colors), marginBottom: spacing.xs, fontSize: '9px' }}>{label}</div>
      <div style={{ fontSize: fontSize.xxl, fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>{value}</div>
    </div>
  );
}

interface TradeSignalsListProps {
  signals: TradeSignal[];
  limit?: number;
}

export function TradeSignalsList({ signals, limit = 10 }: TradeSignalsListProps) {
  const { colors } = useTheme();
  const displaySignals = signals.slice(0, limit);

  return (
    <div style={{ ...cardStyle(colors), height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xl }}>
        <h2 style={{ ...sectionTitle(colors), margin: 0 }}>Recent Signals</h2>
        <span style={{ fontSize: fontSize.lg, color: colors.textMuted, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{signals.length} total</span>
      </div>
      
      {displaySignals.length === 0 ? (
        <div style={emptyState(colors)}>
          <div style={{ fontSize: '32px', marginBottom: spacing.md }}>📡</div>
          <div style={{ fontSize: fontSize.xl, fontWeight: 600 }}>No trade signals</div>
          <div style={{ fontSize: fontSize.md, marginTop: spacing.xs }}>Waiting for agent analysis...</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.lg }}>
          {displaySignals.map((signal) => (<TradeSignalCard key={signal.signalId} signal={signal} />))}
        </div>
      )}
    </div>
  );
}
