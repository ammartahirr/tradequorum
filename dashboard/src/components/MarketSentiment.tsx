import { useTheme } from '../context/ThemeContext';
import type { TradeSignal } from '../types/trading';
import { TradeAction } from '../types/trading';
import { cardStyle, sectionTitle, labelStyle, statusDot, fontSize, spacing, radius } from '../styles/shared';

interface MarketSentimentProps {
  signals: TradeSignal[];
}

export function MarketSentiment({ signals }: MarketSentimentProps) {
  const { colors } = useTheme();

  const recentSignals = signals.slice(0, 10);
  
  let bullishCount = 0;
  let bearishCount = 0;
  let neutralCount = 0;

  recentSignals.forEach(signal => {
    if (signal.action === TradeAction.STRONG_BUY || signal.action === TradeAction.BUY) bullishCount++;
    else if (signal.action === TradeAction.STRONG_SELL || signal.action === TradeAction.SELL) bearishCount++;
    else neutralCount++;
  });

  const total = bullishCount + bearishCount + neutralCount || 1;
  const bullishPct = (bullishCount / total) * 100;
  const bearishPct = (bearishCount / total) * 100;
  const neutralPct = (neutralCount / total) * 100;

  const overallSentiment = bullishPct > bearishPct + 20 ? 'BULLISH' : bearishPct > bullishPct + 20 ? 'BEARISH' : 'NEUTRAL';
  const sentimentColor = overallSentiment === 'BULLISH' ? colors.success : overallSentiment === 'BEARISH' ? colors.error : colors.warning;

  const fearGreedIndex = Math.round(50 + (bullishPct - bearishPct) / 2);
  const fearGreedLabel = fearGreedIndex >= 75 ? 'Extreme Greed' : fearGreedIndex >= 55 ? 'Greed' : fearGreedIndex >= 45 ? 'Neutral' : fearGreedIndex >= 25 ? 'Fear' : 'Extreme Fear';

  return (
    <div style={cardStyle(colors)}>
      <h3 style={{ ...sectionTitle(colors), marginBottom: spacing.xl }}>Market Sentiment Analysis</h3>

      <div style={{ textAlign: 'center', marginBottom: spacing.xl, padding: spacing.xl, backgroundColor: colors.bgTertiary, borderRadius: radius.md, border: `2px solid ${sentimentColor}` }}>
        <div style={{ fontSize: fontSize.sm, color: colors.textMuted, fontWeight: 600, marginBottom: spacing.sm, textTransform: 'uppercase' }}>Overall Market Sentiment</div>
        <div style={{ fontSize: '32px', fontWeight: 800, color: sentimentColor, fontFamily: 'var(--font-mono)', letterSpacing: '0.1em' }}>{overallSentiment}</div>
      </div>

      <div style={{ marginBottom: spacing.xl }}>
        <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>Signal Distribution</div>
        <div style={{ display: 'flex', height: '12px', borderRadius: radius.md, overflow: 'hidden', backgroundColor: colors.bgTertiary }}>
          <div style={{ width: `${bullishPct}%`, backgroundColor: colors.success, transition: 'width 300ms ease' }} />
          <div style={{ width: `${neutralPct}%`, backgroundColor: colors.warning, transition: 'width 300ms ease' }} />
          <div style={{ width: `${bearishPct}%`, backgroundColor: colors.error, transition: 'width 300ms ease' }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: spacing.sm }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
            <div style={statusDot(colors.success)} />
            <span style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>Bullish {bullishPct.toFixed(0)}%</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
            <div style={statusDot(colors.warning)} />
            <span style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>Neutral {neutralPct.toFixed(0)}%</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
            <div style={statusDot(colors.error)} />
            <span style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>Bearish {bearishPct.toFixed(0)}%</span>
          </div>
        </div>
      </div>

      <div style={{ padding: spacing.lg, backgroundColor: colors.bgTertiary, borderRadius: radius.md }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.md }}>
          <span style={labelStyle(colors)}>Fear & Greed Index</span>
          <span style={{ fontSize: fontSize.h3, fontWeight: 800, fontFamily: 'var(--font-mono)', color: fearGreedIndex >= 50 ? colors.success : colors.error }}>{fearGreedIndex}</span>
        </div>
        <div style={{ height: '10px', borderRadius: '5px', background: `linear-gradient(to right, ${colors.error}, ${colors.warning}, ${colors.success})`, position: 'relative' }}>
          <div style={{ position: 'absolute', left: `${fearGreedIndex}%`, top: '-4px', width: '18px', height: '18px', backgroundColor: colors.textPrimary, borderRadius: '50%', transform: 'translateX(-50%)', border: `3px solid ${colors.bgSecondary}`, transition: 'left 300ms ease' }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: spacing.sm, fontSize: fontSize.xs, color: colors.textMuted }}>
          <span>Extreme Fear</span>
          <span style={{ fontWeight: 700, color: colors.textSecondary }}>{fearGreedLabel}</span>
          <span>Extreme Greed</span>
        </div>
      </div>
    </div>
  );
}
