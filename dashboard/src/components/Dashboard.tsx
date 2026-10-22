import { useTradingContext } from '../context/TradingContext';
import { useTheme } from '../context/ThemeContext';
import { Header } from './Header';
import { PositionsTable } from './PositionsTable';
import { TradeHistory } from './TradeHistory';
import { AgentStatusPanel } from './AgentStatusPanel';
import { TradeSignalsList } from './TradeSignalCard';
import { PerformanceMetrics } from './PerformanceMetrics';
import { PortfolioSummary } from './PortfolioSummary';
import { RiskGauge } from './RiskGauge';
import { AgentActivityFeed } from './AgentActivityFeed';
import { LivePositionsGrid } from './LivePositionCard';
import { MarketSentiment } from './MarketSentiment';
import { TradingStats } from './TradingStats';
import { SystemHealth } from './SystemHealth';
import type { ReactNode } from 'react';
import { spacing, fontSize } from '../styles/shared';

export function Dashboard({ nav }: { nav?: ReactNode } = {}) {
  const { state, reconnect } = useTradingContext();
  const { colors } = useTheme();
  const sectionGap = spacing.xxxl; // 32px between major sections
  const gridGap = spacing.xl; // 20px between grid items

  return (
    <div style={{ minHeight: '100vh', backgroundColor: colors.bgPrimary, color: colors.textPrimary, transition: 'background-color 250ms ease, color 250ms ease' }}>
      <Header connectionStatus={state.connectionStatus} onReconnect={reconnect} lastUpdateTime={state.lastUpdateTime} nav={nav} />

      <main style={{ padding: spacing.xxl, maxWidth: '1920px', margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: gridGap, marginBottom: sectionGap }}>
          <PortfolioSummary positions={state.positions} metrics={state.performanceMetrics} />
          <RiskGauge metrics={state.performanceMetrics} />
        </div>

        <div style={{ marginBottom: sectionGap }}>
          <PerformanceMetrics metrics={state.performanceMetrics} />
        </div>

        <div style={{ marginBottom: sectionGap }}>
          <LivePositionsGrid positions={state.positions} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: gridGap, marginBottom: sectionGap }}>
          <AgentStatusPanel statuses={state.agentStatuses} />
          <AgentActivityFeed statuses={state.agentStatuses} />
          <MarketSentiment signals={state.tradeSignals} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: gridGap, marginBottom: sectionGap }}>
          <TradeSignalsList signals={state.tradeSignals} limit={3} />
          <SystemHealth statuses={state.agentStatuses} connectionStatus={state.connectionStatus} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: gridGap, marginBottom: sectionGap }}>
          <PositionsTable positions={state.positions} />
          <TradingStats trades={state.tradeHistory} metrics={state.performanceMetrics} />
        </div>

        <div style={{ marginBottom: sectionGap }}>
          <TradeHistory trades={state.tradeHistory} limit={10} />
        </div>
      </main>

      <footer style={{ padding: `${spacing.lg} ${spacing.xxl}`, borderTop: `1px solid ${colors.border}`, textAlign: 'center', color: colors.textMuted, fontSize: fontSize.md, fontFamily: 'var(--font-mono)' }}>
        AI Trading System v1.0 • Multi-Agent Architecture • Real-time WebSocket Updates
        {state.lastUpdateTime && (<span style={{ marginLeft: spacing.lg }}>Last sync: {new Date(state.lastUpdateTime).toLocaleTimeString()}</span>)}
      </footer>
    </div>
  );
}
