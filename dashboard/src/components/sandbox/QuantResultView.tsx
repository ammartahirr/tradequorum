import { useTheme } from '../../context/ThemeContext';
import { fontSize, spacing } from '../../styles/shared';
import type { QuantResult, QuantTrade } from '../../api/sandbox';
import { BacktestChart } from './BacktestChart';
import { REGIME_COLORS, fmtDate, money, num, pct, toneOf } from './format';
import { Card, EquityChart, KV, Stat, StatGrid, TradeTable } from './ui';

const ALPHA_LABELS: Record<string, string> = {
  momentum: 'Momentum',
  trend: 'Trend',
  breakout: 'Breakout',
  mean_reversion: 'Mean rev.',
  news: 'News',
};

export function QuantResultView({
  result,
  selected,
  setSelected,
}: {
  result: QuantResult;
  selected: number | null;
  setSelected: (i: number | null) => void;
}) {
  const { colors } = useTheme();
  const s = result.stats;
  const c = result.comparison_stats;
  const m = result.meta_model;
  const mc = s.monte_carlo;
  const threshold = Number(result.config.entry_threshold ?? 0.25);

  return (
    <>
      <StatGrid>
        <Stat label="Total return" value={pct(s.total_return_pct, 1)} tone={toneOf(s.total_return_pct)} />
        <Stat label="CAGR" value={pct(s.cagr_pct, 2)} tone={toneOf(s.cagr_pct)} />
        <Stat label="Sharpe" value={num(s.sharpe)} tone={toneOf(s.sharpe, 0.5)} hint="Annualised, from mark-to-market equity" />
        <Stat label="Sortino" value={num(s.sortino)} tone={toneOf(s.sortino, 0.5)} />
        <Stat label="Max drawdown" value={pct(s.max_drawdown_pct, 2)} tone="bad" />
        <Stat label="Calmar" value={num(s.calmar)} tone={toneOf(s.calmar, 0.5)} />
        <Stat
          label="PSR (SR > 0)"
          value={pct(s.psr * 100, 0)}
          tone={s.psr >= 0.95 ? 'good' : s.psr < 0.5 ? 'bad' : 'neutral'}
          hint="Probabilistic Sharpe Ratio: probability the true Sharpe is above 0, given sample length, skew and fat tails"
        />
        <Stat label="Trades" value={`${s.total_trades} (${s.long_trades}L/${s.short_trades}S)`} />
        <Stat label="Win rate" value={pct(s.win_rate * 100)} />
        <Stat label="Profit factor" value={s.profit_factor >= 999 ? '∞' : num(s.profit_factor)} tone={toneOf(s.profit_factor, 1)} />
        <Stat label="Avg R" value={num(s.avg_r)} tone={toneOf(s.avg_r)} hint="Average P&L in units of initial risk" />
        <Stat label="Exposure" value={pct(s.exposure_pct, 0)} />
        <Stat label="Buy & hold" value={pct(s.buy_and_hold_pct, 0)} />
      </StatGrid>

      <section style={{ marginBottom: spacing.xxl }}>
        <Card title={`${result.symbol} · ${result.timeframe} · ${result.source} · quant engine v2`}>
          <div style={{ fontSize: fontSize.md, color: colors.textMuted, fontFamily: 'var(--font-mono)', marginBottom: spacing.md }}>
            {result.bars} bars ({fmtDate(result.first_bar)} → {fmtDate(result.last_bar)}) · first {result.warmup_bars} are warm-up · {result.elapsed_ms} ms
          </div>
          <BacktestChart
            candles={result.candles}
            trades={result.trades}
            selectedIndex={selected}
            onSelectTrade={setSelected}
            regimes={result.regimes}
            composite={result.composite}
            entryThreshold={threshold}
          />
          <div style={{ marginTop: spacing.sm, fontSize: fontSize.md, color: colors.textMuted, display: 'flex', gap: spacing.lg, flexWrap: 'wrap' }}>
            <span>Arrows = entries · dots = exits (green win / red loss) · lower pane = ensemble signal with ±{threshold} entry bands</span>
            {Object.entries(REGIME_COLORS)
              .filter(([k]) => k !== 'transition')
              .map(([k, col]) => (
                <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 12, height: 12, background: col.replace(/0\.\d+\)$/, '0.6)'), borderRadius: 2 }} />
                  {k}
                </span>
              ))}
          </div>
        </Card>
      </section>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: spacing.xl, marginBottom: spacing.xxl }}>
        <Card title="Equity curve">
          <div style={{ height: 260 }}>
            <EquityChart
              data={result.equity_curve}
              compare={result.comparison_equity_curve}
              compareLabel={result.comparison_label}
              positive={s.total_return_pct >= 0}
            />
          </div>
        </Card>
        <Card title="Monte Carlo (1,000 reshuffles)">
          {mc.runs ? (
            <KV
              rows={[
                ['return 5th pct', pct((mc.return_p5 ?? 0) * 100)],
                ['return median', pct((mc.return_p50 ?? 0) * 100)],
                ['return 95th pct', pct((mc.return_p95 ?? 0) * 100)],
                ['max DD median', pct((mc.max_dd_p50 ?? 0) * 100)],
                ['max DD 95th pct', pct((mc.max_dd_p95 ?? 0) * 100)],
                ['P(losing overall)', pct((mc.prob_loss ?? 0) * 100, 0)],
              ]}
            />
          ) : (
            <p style={{ color: colors.textMuted }}>Not enough trades.</p>
          )}
        </Card>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: spacing.xl, marginBottom: spacing.xxl }}>
        <Card title="ML meta-model (walk-forward)">
          <KV
            rows={[
              ['status', result.meta_model_enabled ? 'enabled' : 'disabled (shown as comparison)'],
              ['candidate events', `${m.events} (${m.oos_events} out-of-sample)`],
              ['OOS AUC', num(m.auc, 3)],
              ['base win rate', pct((m.base_rate ?? NaN) * 100)],
              ['refits', m.n_refits],
              ['trusted events', `${m.trusted_events}/${m.events}`],
            ]}
          />
          <p style={{ marginTop: spacing.sm, fontSize: fontSize.md, color: colors.textMuted }}>
            AUC 0.5 = coin flip. The model only sizes trades once it has earned trust: {m.trust_rule}.
          </p>
          {c && (
            <p style={{ marginTop: spacing.sm, fontSize: fontSize.md, color: colors.textSecondary }}>
              {result.comparison_label}: Sharpe {num(c.sharpe)}, return {pct(c.total_return_pct)}, max DD {pct(c.max_drawdown_pct, 2)}
            </p>
          )}
        </Card>
        <Card title="Performance by regime">
          <KV
            rows={Object.entries(result.regime_stats).map(([k, v]) => [
              k,
              `${v.trades} tr · win ${pct(v.win_rate * 100, 0)} · R ${num(v.avg_r)} · ${money(v.pnl)}`,
            ])}
          />
        </Card>
        <Card title="Alpha health (EW Sharpe of own P&L)">
          <KV
            rows={Object.entries(result.alpha_sharpe).map(([k, v]) => [ALPHA_LABELS[k] ?? k, num(v)])}
          />
          <p style={{ marginTop: spacing.sm, fontSize: fontSize.md, color: colors.textMuted }}>
            The ensemble shifts weight toward alphas that are currently working, within regime-based limits.
          </p>
        </Card>
      </div>

      <Card title="Simulated trades">
        {result.trades.length === 0 ? (
          <p style={{ color: colors.textMuted }}>No trades. Try a longer history or different symbol.</p>
        ) : (
          <TradeTable<QuantTrade>
            rows={result.trades}
            selected={selected}
            onSelect={setSelected}
            rowTitle={(t) =>
              Object.entries(t.alpha_contrib)
                .map(([k, v]) => `${ALPHA_LABELS[k] ?? k}: ${v >= 0 ? '+' : ''}${v.toFixed(3)}`)
                .join('  ')
            }
            columns={[
              { header: '#', cell: (_t, i) => i + 1 },
              { header: 'Side', cell: (t) => t.action.toUpperCase(), color: (t) => (t.side === 'long' ? colors.success : colors.error) },
              { header: 'Regime', cell: (t) => t.regime },
              { header: 'Signal', cell: (t) => num(t.composite) },
              { header: 'P(win)', cell: (t) => (t.prob === null ? '—' : `${num(t.prob)}${t.model_trusted ? '' : '*'}`) },
              { header: 'Entry', cell: (t) => fmtDate(t.entry_time) },
              { header: 'Exit', cell: (t) => fmtDate(t.exit_time) },
              { header: 'Entry px', cell: (t) => t.entry_price.toFixed(4) },
              { header: 'SL', cell: (t) => t.stop_loss.toFixed(4), color: () => colors.error },
              { header: 'TP', cell: (t) => t.take_profit.toFixed(4), color: () => colors.success },
              { header: 'Exit px', cell: (t) => t.exit_price.toFixed(4) },
              { header: 'Reason', cell: (t) => t.exit_reason },
              { header: 'Bars', cell: (t) => t.bars_held },
              { header: 'R', cell: (t) => num(t.r_multiple), color: (t) => (t.pnl > 0 ? colors.success : colors.error) },
              { header: 'P&L', cell: (t) => `${money(t.pnl)} (${pct(t.pnl_pct, 2)})`, color: (t) => (t.pnl > 0 ? colors.success : colors.error) },
            ]}
          />
        )}
        <p style={{ marginTop: spacing.sm, fontSize: fontSize.md, color: colors.textMuted }}>
          Hover a row for the alpha breakdown. * = model not trusted yet, so base size was used.
        </p>
      </Card>
    </>
  );
}
