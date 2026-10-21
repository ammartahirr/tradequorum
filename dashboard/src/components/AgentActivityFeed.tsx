import { useTheme } from '../context/ThemeContext';
import type { AgentStatus } from '../types/trading';
import { cardStyle, sectionTitle, fontSize, spacing, radius } from '../styles/shared';

interface AgentActivityFeedProps {
  statuses: AgentStatus[];
}

interface ActivityItem {
  id: string;
  agent: string;
  action: string;
  detail: string;
  timestamp: Date;
  type: 'analysis' | 'signal' | 'decision' | 'alert';
}

function generateActivity(statuses: AgentStatus[]): ActivityItem[] {
  const activities: ActivityItem[] = [];
  const now = new Date();
  
  statuses.forEach((status, idx) => {
    if (status.lastSignalAt) {
      const agentNames: Record<string, string> = { news: 'News Agent', technical: 'Technical Agent', strategy: 'Strategy Agent' };
      const actions: Record<string, string[]> = {
        news: ['Analyzed Reuters feed', 'Processed Bloomberg article', 'Detected sentiment shift', 'Classified impact as CASH_FLOW'],
        technical: ['Calculated RSI indicators', 'Detected support level', 'Found confluence pattern', 'Identified trend reversal'],
        strategy: ['Evaluated trade decision', 'Calculated position size', 'Set stop-loss levels', 'Generated BUY signal'],
      };
      
      const agentActions = actions[status.agentType] || actions.news;
      activities.push({
        id: `${status.agentType}-${idx}`,
        agent: agentNames[status.agentType] || status.agentType,
        action: agentActions[Math.floor(Math.random() * agentActions.length)],
        detail: `Signal #${status.signalCount || 0}`,
        timestamp: new Date(status.lastSignalAt),
        type: status.agentType === 'strategy' ? 'decision' : status.agentType === 'news' ? 'analysis' : 'signal',
      });
    }
  });

  const mockActions = [
    { agent: 'News Agent', action: 'Scanning Reuters for AAPL news', type: 'analysis' as const },
    { agent: 'Technical Agent', action: 'RSI crossed below 30 - Oversold', type: 'signal' as const },
    { agent: 'Strategy Agent', action: 'Evaluating BUY opportunity', type: 'decision' as const },
    { agent: 'Risk Manager', action: 'Position size validated', type: 'alert' as const },
  ];

  mockActions.forEach((mock, i) => {
    activities.push({
      id: `mock-${i}`,
      agent: mock.agent,
      action: mock.action,
      detail: '',
      timestamp: new Date(now.getTime() - i * 30000),
      type: mock.type,
    });
  });

  return activities.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime()).slice(0, 8);
}

export function AgentActivityFeed({ statuses }: AgentActivityFeedProps) {
  const { colors } = useTheme();
  const activities = generateActivity(statuses);

  const typeColors = {
    analysis: colors.info,
    signal: colors.warning,
    decision: colors.success,
    alert: colors.error,
  };

  const typeIcons = {
    analysis: '🔍',
    signal: '📊',
    decision: '🧠',
    alert: '⚠️',
  };

  return (
    <div style={{ ...cardStyle(colors), height: '100%' }}>
      <h3 style={{ ...sectionTitle(colors), marginBottom: spacing.lg }}>Agent Activity Feed</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm, maxHeight: '300px', overflowY: 'auto' }}>
        {activities.map((activity) => (
          <div key={activity.id} style={{ display: 'flex', alignItems: 'flex-start', gap: spacing.md, padding: spacing.sm, backgroundColor: colors.bgTertiary, borderRadius: radius.md, borderLeft: `3px solid ${typeColors[activity.type]}` }}>
            <span style={{ fontSize: fontSize.xxl }}>{typeIcons[activity.type]}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                <span style={{ fontSize: fontSize.sm, fontWeight: 700, color: typeColors[activity.type] }}>{activity.agent}</span>
                <span style={{ fontSize: fontSize.xs, color: colors.textMuted, fontFamily: 'var(--font-mono)' }}>
                  {activity.timestamp.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
              </div>
              <div style={{ fontSize: fontSize.md, color: colors.textSecondary }}>{activity.action}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
