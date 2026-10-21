import { useTheme } from '../context/ThemeContext';
import type { AgentStatus } from '../types/trading';
import { cardStyle, sectionTitle, badge, fontSize, spacing, radius } from '../styles/shared';

interface AgentStatusPanelProps {
  statuses: AgentStatus[];
}

const agentConfig: Record<string, { label: string; icon: string; description: string; role: string }> = {
  news: { label: 'News Agent', icon: '📡', description: 'Market sentiment analysis from news sources', role: 'The Ear' },
  technical: { label: 'Technical Agent', icon: '📊', description: 'Price patterns & indicator analysis', role: 'The Eye' },
  strategy: { label: 'Strategy Agent', icon: '🧠', description: 'Trade decision & risk evaluation', role: 'The Brain' },
};

function formatTime(dateStr: string | undefined): string {
  if (!dateStr) return 'Never';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return date.toLocaleDateString();
}

export function AgentStatusPanel({ statuses }: AgentStatusPanelProps) {
  const { colors } = useTheme();

  const agentTypes = ['news', 'technical', 'strategy'] as const;
  const statusMap = new Map(statuses.map((s) => [s.agentType, s]));

  const statusColors = {
    active: colors.success,
    idle: colors.textMuted,
    error: colors.error,
    stale: colors.warning,
  };

  return (
    <div style={{ ...cardStyle(colors), height: '100%' }}>
      <h2 style={{ ...sectionTitle(colors), marginBottom: spacing.xl }}>Agent Status</h2>
      
      <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
        {agentTypes.map((agentType) => {
          const status = statusMap.get(agentType);
          const agentStatus = status?.status ?? 'idle';
          const config = agentConfig[agentType];
          const statusColor = statusColors[agentStatus as keyof typeof statusColors] || colors.textMuted;
          const statusLabel = agentStatus.toUpperCase();
          
          return (
            <div key={agentType} style={{
              display: 'flex',
              alignItems: 'center',
              gap: spacing.lg,
              padding: spacing.lg,
              backgroundColor: colors.bgTertiary,
              borderRadius: radius.md,
              border: `1px solid ${colors.border}`,
              borderLeft: `4px solid ${statusColor}`,
            }} role="listitem">
              <div style={{
                width: '48px',
                height: '48px',
                backgroundColor: colors.bgSecondary,
                borderRadius: radius.lg,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '24px',
                border: `1px solid ${colors.border}`,
              }}>
                {config.icon}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.xs }}>
                  <span style={{ fontWeight: 700, color: colors.textPrimary, fontSize: fontSize.xl }}>{config.label}</span>
                  <span style={{
                    fontSize: fontSize.sm,
                    color: colors.textMuted,
                    fontWeight: 600,
                    padding: '2px 8px',
                    backgroundColor: colors.bgSecondary,
                    borderRadius: radius.sm,
                    border: `1px solid ${colors.border}`,
                  }}>
                    {config.role}
                  </span>
                </div>
                <div style={{ fontSize: fontSize.md, color: colors.textSecondary, marginBottom: spacing.sm }}>{config.description}</div>
                <div style={{ fontSize: fontSize.sm, color: colors.textMuted, fontFamily: 'var(--font-mono)' }}>
                  Last signal: <span style={{ color: colors.textSecondary, fontWeight: 600 }}>{formatTime(status?.lastSignalAt)}</span>
                </div>
              </div>

              <div style={{ textAlign: 'right' }}>
                <div style={{ ...badge(statusColor, statusColor + '20'), marginBottom: spacing.sm, letterSpacing: '0.1em' }}>{statusLabel}</div>
                {status?.signalCount !== undefined && (
                  <div style={{ fontSize: fontSize.h3, fontWeight: 800, fontFamily: 'var(--font-mono)', color: colors.textPrimary }}>
                    {status.signalCount}
                    <span style={{ fontSize: fontSize.xs, color: colors.textMuted, fontWeight: 600, marginLeft: spacing.xs }}>signals</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
