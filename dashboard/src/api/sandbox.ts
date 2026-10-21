import { API_URL } from '../config';

export type DataSource = 'yahoo' | 'ibkr' | 'synthetic';

export interface Candle {
  time: number; // unix seconds (UTC)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SandboxTrade {
  symbol: string;
  action: string;
  side: 'long' | 'short';
  entry_price: number;
  exit_price: number;
  entry_time: string;
  exit_time: string;
  entry_ts: number;
  exit_ts: number;
  signal_ts: number | null;
  stop_loss: number;
  take_profit: number;
  quantity: number;
  position_size: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: 'tp' | 'sl' | 'timeout' | 'end_of_data';
  bars_held: number;
  conviction: string;
  planned_rr: number;
  r_multiple: number;
  rsi: number;
  confluence: number;
  news_sentiment: string;
  reasoning: string;
}

export interface SandboxStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  total_pnl_pct: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  avg_win: number;
  avg_loss: number;
  avg_risk_reward: number;
  sharpe_ratio: number;
  profit_factor: number;
  expectancy: number;
  avg_r_multiple: number;
  avg_planned_rr: number;
  avg_bars_held: number;
  exposure_pct: number;
  buy_and_hold_pct: number;
  long_trades: number;
  short_trades: number;
  exit_reasons: Record<string, number>;
  action_counts: Record<string, number>;
  bars_evaluated: number;
}

export interface SandboxResult {
  symbol: string;
  timeframe: string;
  source: DataSource;
  bars: number;
  warmup_bars: number;
  first_bar: string;
  last_bar: string;
  config: Record<string, unknown>;
  stats: SandboxStats;
  trades: SandboxTrade[];
  skipped_signals: { time: string; action: string; price: number; reason: string }[];
  equity_curve: { time: number; equity: number }[];
  candles: Candle[];
  elapsed_ms: number;
}

export interface SandboxRequest {
  symbol: string;
  timeframe: string;
  bars: number;
  source?: DataSource;
  horizon?: 'short_term' | 'medium_term' | 'long_term';
  news_mode?: 'momentum' | 'neutral';
  sizing_mode?: 'fixed' | 'strategy';
  max_hold_bars?: number;
  allow_short?: boolean;
  initial_capital?: number;
  commission_pct?: number;
  slippage_pct?: number;
}

export interface SandboxConfig {
  symbols: string[];
  timeframes: string[];
  sources: DataSource[];
  default_source: DataSource;
  max_bars: number;
}

export interface BrokerStatus {
  broker: string;
  connected: boolean;
  paper: boolean;
  default_data_source: string;
  ibkr?: { connected: boolean; host: string; port: number };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? (body as { detail: unknown }).detail
        : body;
    throw new Error(typeof detail === 'string' ? detail : `HTTP ${res.status}: ${JSON.stringify(detail)}`);
  }
  return body as T;
}

export const sandboxApi = {
  config: () => request<SandboxConfig>('/sandbox/config'),
  brokerStatus: () => request<BrokerStatus>('/broker/status'),
  backtest: (req: SandboxRequest) =>
    request<SandboxResult>('/sandbox/backtest', { method: 'POST', body: JSON.stringify(req) }),
};
