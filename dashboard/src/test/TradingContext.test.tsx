import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import React from 'react';
import { TradingProvider, useTradingContext } from '../context/TradingContext';
import type { TradeSignal, Position, TradeRecord, AgentStatus, PerformanceMetrics } from '../types/trading';
import { TradeAction, Conviction, TradingHorizon, PositionStatus } from '../types/trading';

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <TradingProvider websocketUrl="wss://test.example.com/ws">
    {children}
  </TradingProvider>
);

describe('TradingContext', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should provide initial state', async () => {
    const { result } = renderHook(() => useTradingContext(), { wrapper });

    expect(result.current.state.positions).toEqual([]);
    expect(result.current.state.tradeHistory).toEqual([]);
    expect(result.current.state.tradeSignals).toEqual([]);
    expect(result.current.state.agentStatuses).toEqual([]);
    expect(result.current.state.performanceMetrics).toBeNull();
  });

  it('should update positions when dispatch is called', async () => {
    const { result } = renderHook(() => useTradingContext(), { wrapper });

    const mockPosition: Position = {
      tradeId: 'trade-1',
      symbol: 'AAPL',
      action: TradeAction.BUY,
      horizon: TradingHorizon.SHORT_TERM,
      entryPrice: 150.0,
      stopLoss: 145.0,
      takeProfit: 160.0,
      positionSize: 100,
      status: PositionStatus.OPEN,
      conviction: Conviction.HIGH,
      openedAt: new Date().toISOString(),
    };

    act(() => {
      result.current.dispatch({ type: 'UPDATE_POSITION', payload: mockPosition });
    });

    expect(result.current.state.positions).toHaveLength(1);
    expect(result.current.state.positions[0]).toEqual(mockPosition);
  });

  it('should update existing position instead of adding duplicate', async () => {
    const { result } = renderHook(() => useTradingContext(), { wrapper });

    const mockPosition: Position = {
      tradeId: 'trade-1',
      symbol: 'AAPL',
      action: TradeAction.BUY,
      horizon: TradingHorizon.SHORT_TERM,
      entryPrice: 150.0,
      stopLoss: 145.0,
      takeProfit: 160.0,
      positionSize: 100,
      status: PositionStatus.OPEN,
      conviction: Conviction.HIGH,
      openedAt: new Date().toISOString(),
    };

    act(() => {
      result.current.dispatch({ type: 'UPDATE_POSITION', payload: mockPosition });
    });

    const updatedPosition: Position = {
      ...mockPosition,
      pnl: 500,
      pnlPct: 3.33,
    };

    act(() => {
      result.current.dispatch({ type: 'UPDATE_POSITION', payload: updatedPosition });
    });

    expect(result.current.state.positions).toHaveLength(1);
    expect(result.current.state.positions[0].pnl).toBe(500);
  });

  it('should add trade signals and maintain limit', async () => {
    const { result } = renderHook(() => useTradingContext(), { wrapper });

    // Add 60 signals (limit is 50)
    for (let i = 0; i < 60; i++) {
      const signal: TradeSignal = {
        signalId: `signal-${i}`,
        symbol: 'AAPL',
        action: TradeAction.BUY,
        conviction: Conviction.HIGH,
        horizon: TradingHorizon.SHORT_TERM,
        entryPrice: 150.0,
        stopLoss: 145.0,
        takeProfit: 160.0,
        positionSizePct: 0.05,
        riskRewardRatio: 2.0,
        reasoning: 'Test signal',
        timestamp: new Date().toISOString(),
        expiresAt: new Date(Date.now() + 3600000).toISOString(),
      };

      act(() => {
        result.current.dispatch({ type: 'ADD_TRADE_SIGNAL', payload: signal });
      });
    }

    // Should be capped at 50
    expect(result.current.state.tradeSignals).toHaveLength(50);
    // Most recent should be first
    expect(result.current.state.tradeSignals[0].signalId).toBe('signal-59');
  });

  it('should add trade records and maintain limit', async () => {
    const { result } = renderHook(() => useTradingContext(), { wrapper });

    // Add 110 trades (limit is 100)
    for (let i = 0; i < 110; i++) {
      const trade: TradeRecord = {
        tradeId: `trade-${i}`,
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
        openedAt: new Date().toISOString(),
        closedAt: new Date().toISOString(),
      };

      act(() => {
        result.current.dispatch({ type: 'ADD_TRADE_RECORD', payload: trade });
      });
    }

    // Should be capped at 100
    expect(result.current.state.tradeHistory).toHaveLength(100);
    // Most recent should be first
    expect(result.current.state.tradeHistory[0].tradeId).toBe('trade-109');
  });

  it('should update agent status', async () => {
    const { result } = renderHook(() => useTradingContext(), { wrapper });

    const agentStatus: AgentStatus = {
      agentType: 'news',
      status: 'active',
      lastSignalAt: new Date().toISOString(),
      signalCount: 10,
    };

    act(() => {
      result.current.dispatch({ type: 'UPDATE_AGENT_STATUS', payload: agentStatus });
    });

    expect(result.current.state.agentStatuses).toHaveLength(1);
    expect(result.current.state.agentStatuses[0].agentType).toBe('news');

    // Update same agent
    const updatedStatus: AgentStatus = {
      ...agentStatus,
      signalCount: 15,
    };

    act(() => {
      result.current.dispatch({ type: 'UPDATE_AGENT_STATUS', payload: updatedStatus });
    });

    expect(result.current.state.agentStatuses).toHaveLength(1);
    expect(result.current.state.agentStatuses[0].signalCount).toBe(15);
  });

  it('should update performance metrics', async () => {
    const { result } = renderHook(() => useTradingContext(), { wrapper });

    const metrics: PerformanceMetrics = {
      totalTrades: 100,
      winningTrades: 65,
      winRate: 0.65,
      avgRiskReward: 2.1,
      maxDrawdown: 0.08,
      sharpeRatio: 1.5,
    };

    act(() => {
      result.current.dispatch({ type: 'SET_PERFORMANCE_METRICS', payload: metrics });
    });

    expect(result.current.state.performanceMetrics).toEqual(metrics);
  });
});

describe('UI Update Timing (Requirement 8.2)', () => {
  it('should process messages and update state quickly', async () => {
    const { result } = renderHook(() => useTradingContext(), { wrapper });

    const startTime = performance.now();

    const signal: TradeSignal = {
      signalId: 'signal-timing-test',
      symbol: 'AAPL',
      action: TradeAction.STRONG_BUY,
      conviction: Conviction.HIGH,
      horizon: TradingHorizon.SHORT_TERM,
      entryPrice: 150.0,
      stopLoss: 145.0,
      takeProfit: 165.0,
      positionSizePct: 0.05,
      riskRewardRatio: 3.0,
      reasoning: 'Timing test signal',
      timestamp: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 3600000).toISOString(),
    };

    act(() => {
      result.current.dispatch({ type: 'ADD_TRADE_SIGNAL', payload: signal });
    });

    const endTime = performance.now();
    const updateTime = endTime - startTime;

    // State update should be nearly instantaneous (well under 500ms)
    expect(updateTime).toBeLessThan(100);
    expect(result.current.state.tradeSignals).toHaveLength(1);
  });
});
