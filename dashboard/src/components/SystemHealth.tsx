import { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import type { AgentStatus } from '../types/trading';
import { cardStyle, sectionTitle, statBox, labelStyle, statusDot, fontSize, spacing, radius, progressBar } from '../styles/shared';

interface SystemHealthProps {
  statuses: AgentStatus[];
  connectionStatus: string;
}

export function SystemHealth({ statuses, connectionStatus }: SystemHealthProps) {
  const { colors } = useTheme();
  const [uptime, setUptime] = useState(0);

  useEffect(() => {
    const startTime = Date.now();
    const interval = setInterval(() => setUptime(Math.floor((Date.now() - startTime) / 1000)), 1000);
    return () => clearInterval(interval);
  }, []);

  const formatUptime = (seconds: number) => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  const activeAgents = statuses.filter(s => s.status === 'active').length;
  const totalAgents = 3;
  const wsConnected = connectionStatus === 'connected';
  
  const healthScore = Math.round(((activeAgents / totalAgents) * 50) + (wsConnected ? 50 : 0));
  const healthStatus = healthScore >= 80 ? 'HEALTHY' : healthScore >= 50 ? 'DEGRADED' : 'CRITICAL';
  const healthColor = healthScore >= 80 ? colors.success : healthScore >= 50 ? colors.warning : colors.error;

  const cpuUsage = 15 + Math.random() * 20;
  const memoryUsage = 40 + Math.random() * 15;
  const latency = 50 + Math.random() * 100;

  const services = [
    { name: 'WebSocket Connection', status: wsConnected ? 'online' : 'offline', latency: latency.toFixed(0) + 'ms' },
    { name: 'News Agent', status: statuses.find(s => s.agentType === 'news')?.status || 'idle', latency: '120ms' },
    { name: 'Technical Agent', status: statuses.find(s => s.agentType === 'technical')?.status || 'idle', latency: '85ms' },
    { name: 'Strategy Agent', status: statuses.find(s => s.agentType === 'strategy')?.status || 'idle', latency: '45ms' },
    { name: 'Risk Manager', status: 'active', latency: '30ms' },
    { name: 'Order Executor', status: 'active', latency: '150ms' },
  ];

  return (
    <div style={cardStyle(colors)}>
      <h3 style={{ ...sectionTitle(colors), marginBottom: spacing.xl }}>System Health Monitor</h3>

      <div style={{ display: 'flex', gap: spacing.lg, marginBottom: spacing.xl }}>
        <div style={{ ...statBox(colors), flex: 1, border: `2px solid ${healthColor}` }}>
          <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>System Status</div>
          <div style={{ fontSize: '24px', fontWeight: 800, color: healthColor, fontFamily: 'var(--font-mono)' }}>{healthStatus}</div>
          <div style={{ fontSize: fontSize.md, color: colors.textMuted, marginTop: spacing.xs }}>{healthScore}% Health</div>
        </div>
        <div style={{ ...statBox(colors), flex: 1 }}>
          <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>Session Uptime</div>
          <div style={{ fontSize: '24px', fontWeight: 800, color: colors.textPrimary, fontFamily: 'var(--font-mono)' }}>{formatUptime(uptime)}</div>
          <div style={{ fontSize: fontSize.md, color: colors.textMuted, marginTop: spacing.xs }}>HH:MM:SS</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: spacing.sm, marginBottom: spacing.xl }}>
        <ResourceBar label="CPU" value={cpuUsage} colors={colors} />
        <ResourceBar label="Memory" value={memoryUsage} colors={colors} />
        <ResourceBar label="Network" value={latency / 2} colors={colors} />
      </div>

      <div style={{ ...labelStyle(colors), marginBottom: spacing.sm }}>Services</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
        {services.map(service => (
          <div key={service.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: `${spacing.sm} ${spacing.md}`, backgroundColor: colors.bgTertiary, borderRadius: radius.md }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
              <div style={statusDot(service.status === 'active' || service.status === 'online' ? colors.success : service.status === 'idle' ? colors.warning : colors.error)} />
              <span style={{ fontSize: fontSize.md, color: colors.textSecondary }}>{service.name}</span>
            </div>
            <span style={{ fontSize: fontSize.sm, color: colors.textMuted, fontFamily: 'var(--font-mono)' }}>{service.latency}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResourceBar({ label, value, colors }: { label: string; value: number; colors: ReturnType<typeof useTheme>['colors'] }) {
  const barColor = value < 50 ? colors.success : value < 80 ? colors.warning : colors.error;
  return (
    <div style={{ padding: spacing.sm, backgroundColor: colors.bgTertiary, borderRadius: radius.md }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: spacing.sm }}>
        <span style={{ fontSize: fontSize.xs, color: colors.textMuted, fontWeight: 600 }}>{label}</span>
        <span style={{ fontSize: fontSize.sm, color: barColor, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{value.toFixed(0)}%</span>
      </div>
      <div style={{ ...progressBar(colors), height: '4px' }}>
        <div style={{ height: '100%', width: `${value}%`, backgroundColor: barColor, borderRadius: radius.sm }} />
      </div>
    </div>
  );
}
