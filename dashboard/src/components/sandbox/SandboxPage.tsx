import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useTheme } from '../../context/ThemeContext';
import { cardStyle, fontSize, labelStyle, radius, sectionTitle, spacing } from '../../styles/shared';
import {
  sandboxApi,
  type BrokerStatus,
  type DataSource,
  type SandboxRequest,
  type SandboxResult,
} from '../../api/sandbox';
import { BacktestChart } from './BacktestChart';

const DEFAULT_SYMBOLS = ['AAPL', 'MSFT', 'SPY', 'NVDA', 'EURUSD', 'GBPUSD', 'BTCUSD', 'XAUUSD'];
const TIMEFRAMES = ['M15', 'M30', 'H1', 'H4', 'D1', 'W1'];

const money = (v: number) =>
  `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const pct = (v: number, digits = 1) => `${v.toFixed(digits)}%`;
const fmtDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: 'good' | 'bad' | 'neutral' }) {
  const { colors } = useTheme();
  const color = tone === 'good' ? colors.success : tone === 'bad' ? colors.error : colors.textPrimary;
  return (
    <div style={{ ...cardStyle(colors), padding: spacing.lg }}>
      <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>{label}</div>
      <div style={{ fontSize: fontSize.h3, fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>{value}</div>
    </div>
  );
}

export function SandboxPage() {
  const { colors } = useTheme();
  const [form, setForm] = useState<SandboxRequest>({
    symbol: 'AAPL',
    timeframe: 'D1',
    bars: 1500,
    source: 'yahoo',
    news_mode: 'momentum',
    sizing_mode: 'fixed',
    max_hold_bars: 30,
    allow_short: true,
    initial_capital: 100000,
  });
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS);
  const [broker, setBroker] = useState<BrokerStatus | null>(null);
  const [result, setResult] = useState<SandboxResult | null>(null);
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
      const res = await sandboxApi.backtest({ ...form, symbol: form.symbol.trim().toUpperCase() });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [form]);

  const equityData = useMemo(
    () =>
      (result?.equity_curve ?? []).map((p) => ({
        t: new Date(p.time * 1000).toLocaleDateString(),
        equity: Math.round(p.equity * 100) / 100,
      })),
    [result],
  );

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
  const field = (label: string, el: ReactNode) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: spacing.xs, minWidth: 120, flex: 1 }}>
      <span style={labelStyle(colors)}>{label}</span>
      {el}
    </label>
  );

  const s = result?.stats;

  return (
    <main style={{ padding: spacing.xxl, maxWidth: '1920px', margin: '0 auto' }}>
      <section style={{ ...cardStyle(colors), marginBottom: spacing.xxl }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.lg }}>
          <h2 style={sectionTitle(colors)}>Training Sandbox · simulated entries &amp; exits</h2>
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
          style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.lg, alignItems: 'flex-end' }}
        >
          {field(
            'Symbol',
            <>
              <input
                list="sandbox-symbols"
                value={form.symbol}
                onChange={(e) => setForm({ ...form, symbol: e.target.value })}
                style={input}
                aria-label="Symbol"
              />
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
          {field(
            'Bars',
            <input
              type="number"
              min={250}
              max={5000}
              step={50}
              value={form.bars}
              onChange={(e) => setForm({ ...form, bars: Number(e.target.value) })}
              style={input}
            />,
          )}
          {field(
            'Data source',
            <select
              value={form.source}
              onChange={(e) => setForm({ ...form, source: e.target.value as DataSource })}
              style={input}
            >
              <option value="yahoo">Yahoo (free)</option>
              <option value="ibkr">Interactive Brokers</option>
              <option value="synthetic">Synthetic</option>
            </select>,
          )}
          {field(
            'News input',
            <select
              value={form.news_mode}
              onChange={(e) => setForm({ ...form, news_mode: e.target.value as 'momentum' | 'neutral' })}
              style={input}
            >
              <option value="momentum">Momentum proxy</option>
              <option value="neutral">Neutral (tech only)</option>
            </select>,
          )}
          {field(
            'Sizing',
            <select
              value={form.sizing_mode}
              onChange={(e) => setForm({ ...form, sizing_mode: e.target.value as 'fixed' | 'strategy' })}
              style={input}
            >
              <option value="fixed">Fixed 5%</option>
              <option value="strategy">Bot conviction</option>
            </select>,
          )}
          {field(
            'Max hold (bars)',
            <input
              type="number"
              min={1}
              max={500}
              value={form.max_hold_bars}
              onChange={(e) => setForm({ ...form, max_hold_bars: Number(e.target.value) })}
              style={input}
            />,
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, color: colors.textSecondary, fontSize: fontSize.lg }}>
            <input
              type="checkbox"
              checked={form.allow_short}
              onChange={(e) => setForm({ ...form, allow_short: e.target.checked })}
            />
            Allow shorts
          </label>
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
        </form>
        <p style={{ marginTop: spacing.md, fontSize: fontSize.md, color: colors.textMuted, lineHeight: 1.5 }}>
          Replays history through the bot's real Technical + Strategy agents. Signals use the bar close; entries fill
          at the next bar's open with slippage; SL/TP are checked bar by bar (stop assumed first if both touched).
          Historical news is not available, so the News agent is replaced by a momentum proxy. No orders are sent.
        </p>
        {error && (
          <div
            role="alert"
            style={{
              marginTop: spacing.md,
              padding: spacing.md,
              borderRadius: radius.md,
              backgroundColor: colors.errorBg,
              color: colors.error,
              fontFamily: 'var(--font-mono)',
              fontSize: fontSize.lg,
            }}
          >
            {error}
          </div>
        )}
      </section>

      {result && s && (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: spacing.lg,
              marginBottom: spacing.xxl,
            }}
          >
            <Stat label="Trades" value={`${s.total_trades} (${s.long_trades}L/${s.short_trades}S)`} />
            <Stat
              label="Win rate"
              value={pct(s.win_rate * 100)}
              tone={s.total_trades === 0 ? 'neutral' : s.win_rate >= 0.5 ? 'good' : 'bad'}
            />
            <Stat label="Net P&L" value={`${money(s.total_pnl)} (${pct(s.total_pnl_pct, 2)})`} tone={s.total_pnl >= 0 ? 'good' : 'bad'} />
            <Stat label="Buy & hold" value={pct(s.buy_and_hold_pct)} tone="neutral" />
            <Stat label="Max drawdown" value={pct(s.max_drawdown_pct * 100, 2)} tone="bad" />
            <Stat label="Profit factor" value={s.profit_factor >= 999 ? '∞' : s.profit_factor.toFixed(2)} tone={s.profit_factor >= 1 ? 'good' : 'bad'} />
            <Stat label="Sharpe" value={s.sharpe_ratio.toFixed(2)} tone={s.sharpe_ratio > 0 ? 'good' : 'bad'} />
            <Stat label="Avg R multiple" value={s.avg_r_multiple.toFixed(2)} tone={s.avg_r_multiple > 0 ? 'good' : 'bad'} />
            <Stat label="Expectancy / trade" value={money(s.expectancy)} tone={s.expectancy >= 0 ? 'good' : 'bad'} />
            <Stat label="Avg hold" value={`${s.avg_bars_held.toFixed(1)} bars`} />
          </div>

          <section style={{ ...cardStyle(colors), marginBottom: spacing.xxl }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: spacing.md }}>
              <h2 style={sectionTitle(colors)}>
                {result.symbol} · {result.timeframe} · {result.source}
              </h2>
              <span style={{ fontSize: fontSize.md, color: colors.textMuted, fontFamily: 'var(--font-mono)' }}>
                {result.bars} bars ({fmtDate(result.first_bar)} → {fmtDate(result.last_bar)}) · first {result.warmup_bars}{' '}
                are indicator warm-up · {result.elapsed_ms} ms
              </span>
            </div>
            <BacktestChart
              candles={result.candles}
              trades={result.trades}
              selectedIndex={selected}
              onSelectTrade={setSelected}
            />
            <div style={{ marginTop: spacing.sm, fontSize: fontSize.md, color: colors.textMuted }}>
              Arrows = entries (up = bot BUY, down = SELL) · dots = exits (green = win, red = loss) · click a trade
              below or on the chart to draw its entry, stop-loss and take-profit.
            </div>
          </section>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: spacing.xl, marginBottom: spacing.xxl }}>
            <section style={cardStyle(colors)}>
              <h2 style={{ ...sectionTitle(colors), marginBottom: spacing.md }}>Equity curve</h2>
              <div style={{ height: 240 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equityData}>
                    <CartesianGrid stroke={colors.border} strokeDasharray="3 3" />
                    <XAxis dataKey="t" stroke={colors.textMuted} fontSize={11} minTickGap={40} />
                    <YAxis stroke={colors.textMuted} fontSize={11} domain={['auto', 'auto']} width={80} />
                    <Tooltip contentStyle={{ backgroundColor: colors.bgSecondary, border: `1px solid ${colors.border}` }} />
                    <Area
                      type="monotone"
                      dataKey="equity"
                      stroke={s.total_pnl >= 0 ? colors.success : colors.error}
                      fill={s.total_pnl >= 0 ? colors.successBg : colors.errorBg}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </section>
            <section style={cardStyle(colors)}>
              <h2 style={{ ...sectionTitle(colors), marginBottom: spacing.md }}>What the bot decided</h2>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: fontSize.lg, color: colors.textSecondary, lineHeight: 1.8 }}>
                <div>bars evaluated: {s.bars_evaluated}</div>
                {Object.entries(s.action_counts)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => (
                    <div key={k}>
                      {k}: {v}
                    </div>
                  ))}
                <div style={{ marginTop: spacing.sm }}>
                  exits:{' '}
                  {Object.entries(s.exit_reasons)
                    .map(([k, v]) => `${k}=${v}`)
                    .join(' · ') || '—'}
                </div>
                {result.skipped_signals.length > 0 && <div>skipped signals: {result.skipped_signals.length}</div>}
              </div>
            </section>
          </div>

          <section style={cardStyle(colors)}>
            <h2 style={{ ...sectionTitle(colors), marginBottom: spacing.md }}>Simulated trades</h2>
            {result.trades.length === 0 ? (
              <p style={{ color: colors.textMuted, fontSize: fontSize.lg }}>
                The bot took no trades on this data. Its decision matrix only fires at RSI extremes combined with strong
                news/momentum — try more bars, another symbol, or a lower timeframe.
              </p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: fontSize.lg }}>
                  <thead>
                    <tr style={{ textAlign: 'left', color: colors.textLabel }}>
                      {['#', 'Side', 'Entry', 'Exit', 'Entry px', 'SL', 'TP', 'Exit px', 'Reason', 'Bars', 'R', 'P&L', 'RSI', 'Conf.'].map(
                        (h) => (
                          <th key={h} style={{ padding: spacing.sm, borderBottom: `1px solid ${colors.border}`, ...labelStyle(colors) }}>
                            {h}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => {
                      const active = selected === i;
                      const pnlColor = t.pnl > 0 ? colors.success : colors.error;
                      return (
                        <tr
                          key={i}
                          onClick={() => setSelected(active ? null : i)}
                          title={t.reasoning}
                          style={{
                            cursor: 'pointer',
                            backgroundColor: active ? colors.bgHover : 'transparent',
                            color: colors.textPrimary,
                          }}
                        >
                          <td style={{ padding: spacing.sm }}>{i + 1}</td>
                          <td style={{ padding: spacing.sm, color: t.side === 'long' ? colors.success : colors.error }}>
                            {t.action.toUpperCase()}
                          </td>
                          <td style={{ padding: spacing.sm }}>{fmtDate(t.entry_time)}</td>
                          <td style={{ padding: spacing.sm }}>{fmtDate(t.exit_time)}</td>
                          <td style={{ padding: spacing.sm }}>{t.entry_price.toFixed(4)}</td>
                          <td style={{ padding: spacing.sm, color: colors.error }}>{t.stop_loss.toFixed(4)}</td>
                          <td style={{ padding: spacing.sm, color: colors.success }}>{t.take_profit.toFixed(4)}</td>
                          <td style={{ padding: spacing.sm }}>{t.exit_price.toFixed(4)}</td>
                          <td style={{ padding: spacing.sm }}>{t.exit_reason}</td>
                          <td style={{ padding: spacing.sm }}>{t.bars_held}</td>
                          <td style={{ padding: spacing.sm, color: pnlColor }}>{t.r_multiple.toFixed(2)}</td>
                          <td style={{ padding: spacing.sm, color: pnlColor }}>
                            {money(t.pnl)} ({pct(t.pnl_pct, 2)})
                          </td>
                          <td style={{ padding: spacing.sm }}>{t.rsi.toFixed(1)}</td>
                          <td style={{ padding: spacing.sm }}>{t.confluence.toFixed(2)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
