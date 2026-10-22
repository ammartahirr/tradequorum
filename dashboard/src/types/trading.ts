// Enums matching the backend Python models
export enum Sentiment {
  VERY_BULLISH = 'very_bullish',
  BULLISH = 'bullish',
  NEUTRAL = 'neutral',
  BEARISH = 'bearish',
  VERY_BEARISH = 'very_bearish',
}

export enum ImpactType {
  CASH_FLOW = 'cash_flow',
  HYPE = 'hype',
  REGULATORY = 'regulatory',
  MACRO = 'macro',
}

export enum TrendDirection {
  STRONG_UPTREND = 'strong_uptrend',
  UPTREND = 'uptrend',
  SIDEWAYS = 'sideways',
  DOWNTREND = 'downtrend',
  STRONG_DOWNTREND = 'strong_downtrend',
}

export enum MarketCondition {
  OVERSOLD = 'oversold',
  NEUTRAL = 'neutral',
  OVERBOUGHT = 'overbought',
}

export enum TradeAction {
  STRONG_BUY = 'strong_buy',
  BUY = 'buy',
  WAIT_PULLBACK = 'wait_pullback',
  HOLD = 'hold',
  SELL = 'sell',
  STRONG_SELL = 'strong_sell',
  NO_TRADE = 'no_trade',
}

export enum TradingHorizon {
  SHORT_TERM = 'short_term',
  MEDIUM_TERM = 'medium_term',
  LONG_TERM = 'long_term',
}

export enum Conviction {
  HIGH = 'high',
  MEDIUM = 'medium',
  LOW = 'low',
}

export enum PositionStatus {
  OPEN = 'open',
  CLOSED_PROFIT = 'closed_profit',
  CLOSED_LOSS = 'closed_loss',
  CLOSED_SL = 'closed_sl',
  CLOSED_TP = 'closed_tp',
}

// Data interfaces
export interface NewsSignal {
  signalId: string;
  symbol: string;
  sentiment: Sentiment;
  impactType: ImpactType;
  impactScore: number;
  confidence: number;
  reasoning: string;
  sourceItems: string[];
  timestamp: string;
  expiresAt: string;
}

export interface ConfluenceResult {
  score: number;
  factors: string[];
  description: string;
}

export interface TechnicalSignal {
  signalId: string;
  symbol: string;
  trend: TrendDirection;
  condition: MarketCondition;
  rsi: number;
  currentPrice: number;
  supportLevels: number[];
  resistanceLevels: number[];
  confluence: ConfluenceResult;
  volumeTrend: string;
  timestamp: string;
}

export interface TradeSignal {
  signalId: string;
  symbol: string;
  action: TradeAction;
  conviction: Conviction;
  horizon: TradingHorizon;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  positionSizePct: number;
  riskRewardRatio: number;
  reasoning: string;
  timestamp: string;
  expiresAt: string;
}

export interface Position {
  tradeId: string;
  symbol: string;
  action: TradeAction;
  horizon: TradingHorizon;
  entryPrice: number;
  exitPrice?: number;
  stopLoss: number;
  takeProfit: number;
  positionSize: number;
  status: PositionStatus;
  pnl?: number;
  pnlPct?: number;
  conviction: Conviction;
  openedAt: string;
  closedAt?: string;
}

export interface TradeRecord {
  tradeId: string;
  symbol: string;
  action: TradeAction;
  horizon: TradingHorizon;
  entryPrice: number;
  exitPrice?: number;
  stopLoss: number;
  takeProfit: number;
  positionSize: number;
  status: PositionStatus;
  pnl?: number;
  pnlPct?: number;
  conviction: Conviction;
  reasoning: string;
  openedAt: string;
  closedAt?: string;
}

export interface PerformanceMetrics {
  totalTrades: number;
  winningTrades: number;
  winRate: number;
  avgRiskReward: number;
  maxDrawdown: number;
  sharpeRatio: number;
}

export interface AgentStatus {
  agentType: 'news' | 'technical' | 'strategy';
  status: 'active' | 'idle' | 'error' | 'stale';
  lastSignalAt?: string;
  signalCount: number;
}

// WebSocket message types
export type WebSocketMessageType =
  | 'trade_signal'
  | 'position_update'
  | 'trade_executed'
  | 'agent_status'
  | 'performance_update'
  | 'connection_status'
  | 'error'
  | 'pong'
  | 'news_signal'
  | 'technical_signal'
  | 'risk_alert';

export interface WebSocketMessage {
  type: WebSocketMessageType;
  payload: unknown;
  /** legacy backend key – normalised into payload */
  data?: unknown;
  timestamp: string;
}

export interface TradeSignalMessage extends WebSocketMessage {
  type: 'trade_signal';
  payload: TradeSignal;
}

export interface PositionUpdateMessage extends WebSocketMessage {
  type: 'position_update';
  payload: Position;
}

export interface TradeExecutedMessage extends WebSocketMessage {
  type: 'trade_executed';
  payload: TradeRecord;
}

export interface AgentStatusMessage extends WebSocketMessage {
  type: 'agent_status';
  payload: AgentStatus;
}

export interface PerformanceUpdateMessage extends WebSocketMessage {
  type: 'performance_update';
  payload: PerformanceMetrics;
}
