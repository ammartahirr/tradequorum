import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '../context/ThemeContext';
import { ConnectionStatus } from '../components/ConnectionStatus';
import { PositionsTable } from '../components/PositionsTable';
import { TradeHistory } from '../components/TradeHistory';
import { AgentStatusPanel } from '../components/AgentStatusPanel';
import { TradeSignalCard, TradeSignalsList } from '../components/TradeSignalCard';
import { PerformanceMetrics } from '../components/PerformanceMetrics';
import type { Position, TradeRecord, TradeSignal, AgentStatus, PerformanceMetrics as PerformanceMetricsType } from '../types/trading';
import { TradeAction, Conviction, TradingHorizon, PositionStatus } from '../types/trading';
import { ReactNode } from 'react';

// Wrapper component for tests that need ThemeProvider
function TestWrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

// Custom render function that wraps with ThemeProvider
function renderWithTheme(ui: ReactNode) {
  return render(<TestWrapper>{ui}</TestWrapper>);
}

describe('ConnectionStatus', () => {
  it('should display connected status', () => {
    renderWithTheme(<ConnectionStatus status="connected" />);
    expect(screen.getByText('Connected')).toBeInTheDocument();
  });

  it('should display connecting status', () => {
    renderWithTheme(<ConnectionStatus status="connecting" />);
    expect(screen.getByText('Connecting')).toBeInTheDocument();
  });

  it('should display reconnecting status', () => {
    renderWithTheme(<ConnectionStatus status="reconnecting" />);
    expect(screen.getByText('Reconnecting')).toBeInTheDocument();
  });

  it('should display disconnected status with reconnect button', () => {
    const onReconnect = vi.fn();
    renderWithTheme(<ConnectionStatus status="disconnected" onReconnect={onReconnect} />);
    
    expect(screen.getByText('Disconnected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reconnect/i })).toBeInTheDocument();
  });

  it('should call onReconnect when button is clicked', async () => {
    const user = userEvent.setup();
    const onReconnect = vi.fn();
    renderWithTheme(<ConnectionStatus status="disconnected" onReconnect={onReconnect} />);
    
    await user.click(screen.getByRole('button', { name: /reconnect/i }));
    expect(onReconnect).toHaveBeenCalledTimes(1);
  });
});

describe('PositionsTable', () => {
  const mockPositions: Position[] = [
    {
      tradeId: 'trade-1',
      symbol: 'AAPL',
      action: TradeAction.BUY,
      horizon: TradingHorizon.SHORT_TERM,
      entryPrice: 150.0,
      stopLoss: 145.0,
      takeProfit: 160.0,
      positionSize: 100,
      status: PositionStatus.OPEN,
      pnl: 250,
      pnlPct: 1.67,
      conviction: Conviction.HIGH,
      openedAt: '2024-01-15T10:30:00Z',
    },
  ];

  it('should display open positions', () => {
    renderWithTheme(<PositionsTable positions={mockPositions} />);
    
    expect(screen.getByText('Open Positions')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('$150.00')).toBeInTheDocument();
    expect(screen.getByText('$145.00')).toBeInTheDocument();
    expect(screen.getByText('$160.00')).toBeInTheDocument();
  });

  it('should display empty state when no positions', () => {
    renderWithTheme(<PositionsTable positions={[]} />);
    
    expect(screen.getByText('Open Positions')).toBeInTheDocument();
    expect(screen.getByText('No open positions')).toBeInTheDocument();
  });

  it('should filter out closed positions', () => {
    const closedPosition: Position = {
      ...mockPositions[0],
      tradeId: 'trade-2',
      status: PositionStatus.CLOSED_PROFIT,
    };
    
    renderWithTheme(<PositionsTable positions={[...mockPositions, closedPosition]} />);
    // Should only show 1 open position
    expect(screen.getByText('1')).toBeInTheDocument();
  });
});

describe('TradeHistory', () => {
  const mockTrades: TradeRecord[] = [
    {
      tradeId: 'trade-1',
      symbol: 'AAPL',
      action: TradeAction.BUY,
      horizon: TradingHorizon.SHORT_TERM,
      entryPrice: 150.0,
      exitPrice: 155.0,
      stopLoss: 145.0,
      takeProfit: 160.0,
      positionSize: 100,
      status: PositionStatus.CLOSED_PROFIT,
      pnl: 500,
      pnlPct: 3.33,
      conviction: Conviction.HIGH,
      reasoning: 'Test trade',
      openedAt: '2024-01-15T10:30:00Z',
      closedAt: '2024-01-16T14:00:00Z',
    },
  ];

  it('should display trade history', () => {
    renderWithTheme(<TradeHistory trades={mockTrades} />);
    
    expect(screen.getByText('Trade History')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    // P&L is displayed in multiple places, use getAllByText
    expect(screen.getAllByText('+500.00').length).toBeGreaterThan(0);
  });

  it('should display empty state when no trades', () => {
    renderWithTheme(<TradeHistory trades={[]} />);
    expect(screen.getByText('No trade history')).toBeInTheDocument();
  });

  it('should respect limit prop', () => {
    const manyTrades = Array.from({ length: 30 }, (_, i) => ({
      ...mockTrades[0],
      tradeId: `trade-${i}`,
    }));
    
    renderWithTheme(<TradeHistory trades={manyTrades} limit={5} />);
    
    // Should only show 5 trade items
    const symbols = screen.getAllByText('AAPL');
    expect(symbols).toHaveLength(5);
  });
});

describe('AgentStatusPanel', () => {
  const mockStatuses: AgentStatus[] = [
    {
      agentType: 'news',
      status: 'active',
      lastSignalAt: new Date().toISOString(),
      signalCount: 10,
    },
    {
      agentType: 'technical',
      status: 'idle',
      signalCount: 5,
    },
  ];

  it('should display all agent types', () => {
    renderWithTheme(<AgentStatusPanel statuses={mockStatuses} />);
    
    expect(screen.getByText('News Agent')).toBeInTheDocument();
    expect(screen.getByText('Technical Agent')).toBeInTheDocument();
    expect(screen.getByText('Strategy Agent')).toBeInTheDocument();
  });

  it('should display signal counts', () => {
    renderWithTheme(<AgentStatusPanel statuses={mockStatuses} />);
    
    expect(screen.getByText(/10/)).toBeInTheDocument();
    expect(screen.getByText(/5/)).toBeInTheDocument();
  });
});

describe('TradeSignalCard', () => {
  const mockSignal: TradeSignal = {
    signalId: 'signal-1',
    symbol: 'AAPL',
    action: TradeAction.STRONG_BUY,
    conviction: Conviction.HIGH,
    horizon: TradingHorizon.SHORT_TERM,
    entryPrice: 150.0,
    stopLoss: 145.0,
    takeProfit: 165.0,
    positionSizePct: 0.05,
    riskRewardRatio: 3.0,
    reasoning: 'Strong bullish momentum with technical confluence',
    timestamp: '2024-01-15T10:30:00Z',
    expiresAt: '2024-01-15T14:30:00Z',
  };

  it('should display signal details (Requirement 8.3)', () => {
    renderWithTheme(<TradeSignalCard signal={mockSignal} />);
    
    // Symbol
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    // Action (format is "STRONG BUY" without underscore)
    expect(screen.getByText(/STRONG BUY/i)).toBeInTheDocument();
    // Entry price
    expect(screen.getByText('$150.00')).toBeInTheDocument();
    // Stop loss
    expect(screen.getByText('$145.00')).toBeInTheDocument();
    // Take profit
    expect(screen.getByText('$165.00')).toBeInTheDocument();
    // Reasoning
    expect(screen.getByText('Strong bullish momentum with technical confluence')).toBeInTheDocument();
  });

  it('should display risk-reward ratio', () => {
    renderWithTheme(<TradeSignalCard signal={mockSignal} />);
    expect(screen.getByText('3.00')).toBeInTheDocument();
  });

  it('should display position size percentage', () => {
    renderWithTheme(<TradeSignalCard signal={mockSignal} />);
    expect(screen.getByText('5.0%')).toBeInTheDocument();
  });
});

describe('TradeSignalsList', () => {
  it('should display empty state when no signals', () => {
    renderWithTheme(<TradeSignalsList signals={[]} />);
    expect(screen.getByText('No trade signals')).toBeInTheDocument();
  });

  it('should respect limit prop', () => {
    const mockSignal: TradeSignal = {
      signalId: 'signal-1',
      symbol: 'AAPL',
      action: TradeAction.BUY,
      conviction: Conviction.MEDIUM,
      horizon: TradingHorizon.SHORT_TERM,
      entryPrice: 150.0,
      stopLoss: 145.0,
      takeProfit: 160.0,
      positionSizePct: 0.03,
      riskRewardRatio: 2.0,
      reasoning: 'Test',
      timestamp: new Date().toISOString(),
      expiresAt: new Date().toISOString(),
    };

    const signals = Array.from({ length: 20 }, (_, i) => ({
      ...mockSignal,
      signalId: `signal-${i}`,
    }));

    renderWithTheme(<TradeSignalsList signals={signals} limit={3} />);
    
    const articles = screen.getAllByRole('article');
    expect(articles).toHaveLength(3);
  });
});

describe('PerformanceMetrics', () => {
  const mockMetrics: PerformanceMetricsType = {
    totalTrades: 100,
    winningTrades: 65,
    winRate: 0.65,
    avgRiskReward: 2.1,
    maxDrawdown: 0.08,
    sharpeRatio: 1.5,
  };

  it('should display all metrics (Requirement 8.4)', () => {
    renderWithTheme(<PerformanceMetrics metrics={mockMetrics} />);
    
    // Total trades
    expect(screen.getByText('100')).toBeInTheDocument();
    // Winning trades
    expect(screen.getByText('65')).toBeInTheDocument();
    // Win rate
    expect(screen.getByText('65.0%')).toBeInTheDocument();
    // Avg R:R ratio
    expect(screen.getByText('2.10')).toBeInTheDocument();
    // Max drawdown
    expect(screen.getByText('8.0%')).toBeInTheDocument();
    // Sharpe ratio
    expect(screen.getByText('1.50')).toBeInTheDocument();
  });

  it('should display empty state when no metrics', () => {
    renderWithTheme(<PerformanceMetrics metrics={null} />);
    expect(screen.getByText('No performance data available')).toBeInTheDocument();
  });
});
