import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { useTheme } from '../../context/ThemeContext';
import { cardStyle, fontSize, labelStyle, radius, sectionTitle, spacing } from '../../styles/shared';
import {
  sandboxApi,
  type BrokerStatus,
  type DataSource,
  type Engine,
  type QuantParams,
  type QuantResult,
  type SandboxRequest,
  type SandboxResult,
  type SandboxTrade,
} from '../../api/sandbox';
import { BacktestChart } from './BacktestChart';
import { QuantResultView } from './QuantResultView';
import { fmtDate, money, num, pct, toneOf } from './format';
import { Card, EquityChart, KV, Stat, StatGrid, TradeTable } from './ui';

const DEFAULT_SYMBOLS = ['AAPL', 'MSFT', 'SPY', 'QQQ', 'NVDA', 'JPM', 'GLD', 'EURUSD', 'GBPUSD', 'BTCUSD', 'ETHUSD'];
const TIMEFRAMES = ['M15', 'M30', 'H1', 'H4', 'D1', 'W1'];

function ClassicResultView({
  result,
  selected,
  setSelected,
}: {
  result: SandboxResult;
  selected: number | null;
  setSelected: (i: number | null) => void;
}) {
  const { colors } = useTheme();
  const s = result.stats;
  return (
    <>
      <StatGrid>
        <Stat label="Trades" value={`${s.total_trades} (${s.long_trades}L/${s.short_trades}S)`} />
        <Stat label="Win rate" value={pct(s.win_rate * 100)} />
        <Stat label="Net P&L" value={`${money(s.total_pnl)} (${pct(s.total_pnl_pct, 2)})`} tone={toneOf(s.total_pnl)} />
        <Stat label="Max drawdown" value={pct(s.max_drawdown_pct * 100, 2)} tone="bad" />
        <Stat label="Sharpe" value={num(s.sharpe_ratio)} tone={toneOf(s.sharpe_ratio)} />
        <Stat label="Profit factor" value={s.profit_factor >= 999 ? '∞' : num(s.profit_factor)} tone={toneOf(s.profit_factor, 1)} />
        <Stat label="Buy & hold" value={pct(s.buy_and_hold_pct)} />
      </StatGrid>
      <section style={{ marginBottom: spacing.xxl }}>
        <Card title={`${result.symbol} · ${result.timeframe} · ${result.source} · classic v1 decision matrix`}>
          <BacktestChart candles={result.candles} trades={result.trades} selectedIndex={selected} onSelectTrade={setSelected} />
        </Card>
      </section>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: spacing.xl, marginBottom: spacing.xxl }}>
        <Card title="Equity curve">
          <div style={{ height: 240 }}>
            <EquityChart data={result.equity_curve} positive={s.total_pnl >= 0} />
          </div>
        </Card>
        <Card title="What the bot decided">
          <KV rows={Object.entries(s.action_counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, v])} />
        </Card>
      </div>
      <Card title="Simulated trades">
        <TradeTable<SandboxTrade>
          rows={result.trades}
          selected={selected}
          onSelect={setSelected}
          rowTitle={(t) => t.reasoning}
          columns={[
            { header: '#', cell: (_t, i) => i + 1 },
            { header: 'Side', cell: (t) => t.action.toUpperCase(), color: (t) => (t.side === 'long' ? colors.success : colors.error) },
            { header: 'Entry', cell: (t) => fmtDate(t.entry_time) },
            { header: 'Exit', cell: (t) => fmtDate(t.exit_time) },
            { header: 'Entry px', cell: (t) => t.entry_price.toFixed(4) },
            { header: 'SL', cell: (t) => t.stop_loss.toFixed(4) },
            { header: 'TP', cell: (t) => t.take_profit.toFixed(4) },
            { header: 'Exit px', cell: (t) => t.exit_price.toFixed(4) },
            { header: 'Reason', cell: (t) => t.exit_reason },
            { header: 'P&L', cell: (t) => money(t.pnl), color: (t) => (t.pnl > 0 ? colors.success : colors.error) },
          ]}
        />
      </Card>
    </>
  );
}

export function SandboxPage() {
  const { colors } = useTheme();
  const [form, setForm] = useState<SandboxRequest>({
    engine: 'quant',
    symbol: 'MSFT',
    timeframe: 'D1',
    bars: 3000,
    source: 'yahoo',
    news_mode: 'momentum',
    sizing_mode: 'fixed',
    max_hold_bars: 40,
    allow_short: true,
    initial_capital: 100000,
  });
  const [quant, setQuant] = useState<QuantParams>({
    use_meta_model: false,
    sl_atr: 2.0,
    tp_atr: 3.0,
    trail_atr: 2.5,
    base_risk: 0.005,
    commission_bps: 2,
    slippage_bps: 3,
    trend_filter: true,
  });
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS);
  const [broker, setBroker] = useState<BrokerStatus | null>(null);
  const [result, setResult] = useState<SandboxResult | QuantResult | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    sandboxApi
      .config()
      .then((cfg) => {
        setSymbols(Array.from(new Set([...cfg.symbols, ...DEFAULT_SYMBOLS])));
        setForm((f) => ({ ...f, source: cfg.default_source }));
      })
      .catch(() => undefined);
    sandboxApi.brokerStatus().then(setBroker).catch(() => undefined);
  }, []);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSelected(null);
    try {
      const req: SandboxRequest = { ...form, symbol: form.symbol.trim().toUpperCase() };
      if (form.engine === 'quant') req.quant = quant;
      setResult(await sandboxApi.backtest(req));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [form, quant]);

  const input: CSSProperties = {
    width: '100%',
    padding: `${spacing.sm} ${spacing.md}`,
    backgroundColor: colors.bgTertiary,
    color: colors.textPrimary,
    border: `1px solid ${colors.border}`,
    borderRadius: radius.md,
    fontFamily: 'var(--font-mono)',
    fontSize: fontSize.lg,
  };
  const field = (label: string, el: ReactNode, hint?: string) => (
    <label title={hint} style={{ display: 'flex', flexDirection: 'column', gap: spacing.xs, minWidth: 110, flex: 1 }}>
      <span style={labelStyle(colors)}>{label}</span>
      {el}
    </label>
  );
  const numberField = (label: string, value: number | undefined, onChange: (v: number) => void, step: number, hint?: string) =>
    field(label, <input type="number" step={step} value={value ?? ''} onChange={(e) => onChange(Number(e.target.value))} style={input} />, hint);
  const check = (label: string, checked: boolean, onChange: (v: boolean) => void, hint?: string) => (
    <label title={hint} style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, color: colors.textSecondary, fontSize: fontSize.lg }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
  const isQuant = form.engine === 'quant';

  return (
    <main style={{ padding: spacing.xxl, maxWidth: '1920px', margin: '0 auto' }}>
      <section style={{ ...cardStyle(colors), marginBottom: spacing.xxl }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.lg }}>
          <h2 style={sectionTitle(colors)}>Training Sandbox · walk-forward backtest</h2>
          {broker && (
            <span style={{ fontSize: fontSize.md, fontFamily: 'var(--font-mono)', color: colors.textMuted }}>
              broker: {broker.broker} {broker.connected ? '● connected' : '○ offline'}
              {broker.ibkr && ` · IBKR ${broker.ibkr.connected ? 'connected' : 'not connected'} (${broker.ibkr.host}:${broker.ibkr.port})`}
            </span>
          )}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run();
          }}
          style={{ display: 'flex', flexDirection: 'column', gap: spacing.lg }}
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.lg, alignItems: 'flex-end' }}>
            {field(
              'Engine',
              <select value={form.engine} onChange={(e) => setForm({ ...form, engine: e.target.value as Engine })} style={input}>
                <option value="quant">Quant v2 (regimes + ensemble)</option>
                <option value="classic">Classic v1 (decision matrix)</option>
              </select>,
            )}
            {field(
              'Symbol',
              <>
                <input list="sandbox-symbols" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} style={input} aria-label="Symbol" />
                <datalist id="sandbox-symbols">
                  {symbols.map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
              </>,
            )}
            {field(
              'Timeframe',
              <select value={form.timeframe} onChange={(e) => setForm({ ...form, timeframe: e.target.value })} style={input}>
                {TIMEFRAMES.map((tf) => (
                  <option key={tf}>{tf}</option>
                ))}
              </select>,
            )}
            {numberField('Bars', form.bars, (v) => setForm({ ...form, bars: v }), 100)}
            {field(
              'Data source',
              <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value as DataSource })} style={input}>
                <option value="yahoo">Yahoo (free)</option>
                <option value="ibkr">Interactive Brokers</option>
                <option value="synthetic">Synthetic</option>
              </select>,
            )}
            {numberField('Max hold (bars)', form.max_hold_bars, (v) => setForm({ ...form, max_hold_bars: v }), 1)}
            {check('Allow shorts', Boolean(form.allow_short), (v) => setForm({ ...form, allow_short: v }))}
          </div>
          {isQuant && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.lg, alignItems: 'flex-end' }}>
              {numberField('Stop (×ATR)', quant.sl_atr, (v) => setQuant({ ...quant, sl_atr: v }), 0.1)}
              {numberField('Target (×ATR)', quant.tp_atr, (v) => setQuant({ ...quant, tp_atr: v }), 0.1)}
              {numberField('Trail (×ATR)', quant.trail_atr, (v) => setQuant({ ...quant, trail_atr: v }), 0.1)}
              {numberField('Risk / trade', quant.base_risk, (v) => setQuant({ ...quant, base_risk: v }), 0.001, 'Fraction of equity lost if the stop is hit (0.005 = 0.5%)')}
              {numberField('Commission (bps)', quant.commission_bps, (v) => setQuant({ ...quant, commission_bps: v }), 0.5)}
              {numberField('Slippage (bps)', quant.slippage_bps, (v) => setQuant({ ...quant, slippage_bps: v }), 0.5)}
              {check('Trend filter (200)', Boolean(quant.trend_filter), (v) => setQuant({ ...quant, trend_filter: v }))}
              {check('ML meta-model sizing', Boolean(quant.use_meta_model), (v) => setQuant({ ...quant, use_meta_model: v }),
                'Walk-forward gradient boosting + logistic model predicts P(win) and sizes trades with fractional Kelly once it has earned trust')}
            </div>
          )}
          <div>
            <button
              type="submit"
              disabled={loading}
              style={{
                padding: `${spacing.md} ${spacing.xxl}`,
                backgroundColor: colors.textPrimary,
                color: colors.bgPrimary,
                border: 'none',
                borderRadius: radius.md,
                fontWeight: 800,
                fontSize: fontSize.lg,
                cursor: loading ? 'wait' : 'pointer',
                opacity: loading ? 0.6 : 1,
              }}
            >
              {loading ? 'Running…' : 'Run backtest'}
            </button>
          </div>
        </form>
        <p style={{ marginTop: spacing.md, fontSize: fontSize.md, color: colors.textMuted, lineHeight: 1.5 }}>
          {isQuant
            ? 'Quant v2: causal features → regime detection → momentum / trend / breakout / mean-reversion alphas weighted by regime and by their own recent performance → ATR stops, breakeven + chandelier trail, vol-targeted risk sizing, drawdown throttle. Optional walk-forward ML meta-model (purged + embargoed). Signals at bar close, fills next open, costs included. No orders are sent.'
            : 'Classic v1: the original News × Technical decision matrix with a momentum proxy for news. Kept for comparison.'}
        </p>
        {error && (
          <div role="alert" style={{ marginTop: spacing.md, padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.errorBg, color: colors.error, fontFamily: 'var(--font-mono)', fontSize: fontSize.lg }}>
            {error}
          </div>
        )}
      </section>

      {result && result.engine === 'quant_v2' && <QuantResultView result={result} selected={selected} setSelected={setSelected} />}
      {result && result.engine === 'classic' && <ClassicResultView result={result} selected={selected} setSelected={setSelected} />}
    </main>
  );
}
