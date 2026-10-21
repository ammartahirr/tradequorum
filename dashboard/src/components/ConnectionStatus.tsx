import { useTheme } from '../context/ThemeContext';
import { fontSize, spacing, radius } from '../styles/shared';
import type { ConnectionStatus as ConnectionStatusType } from '../hooks/useWebSocket';

interface ConnectionStatusProps {
  status: ConnectionStatusType;
  onReconnect?: () => void;
}

export function ConnectionStatus({ status, onReconnect }: ConnectionStatusProps) {
  const { colors } = useTheme();

  const statusConfig = {
    connected: { color: colors.success, label: 'Connected', icon: '●' },
    connecting: { color: colors.warning, label: 'Connecting', icon: '◐' },
    reconnecting: { color: colors.warning, label: 'Reconnecting', icon: '◐' },
    disconnected: { color: colors.error, label: 'Disconnected', icon: '○' },
  };

  const config = statusConfig[status];

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md }} role="status" aria-live="polite">
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, padding: `${spacing.sm} ${spacing.lg}`, backgroundColor: colors.bgTertiary, border: `1px solid ${colors.border}`, borderRadius: radius.md, fontSize: fontSize.lg, fontFamily: 'var(--font-mono)' }}>
        <span style={{ color: config.color, animation: status === 'connecting' || status === 'reconnecting' ? 'spin 1s linear infinite' : 'none', fontSize: fontSize.xl }}>{config.icon}</span>
        <span style={{ color: colors.textSecondary, fontWeight: 600 }}>{config.label}</span>
      </div>
      
      {status === 'disconnected' && onReconnect && (
        <button
          onClick={onReconnect}
          style={{ padding: `${spacing.sm} ${spacing.lg}`, backgroundColor: colors.textPrimary, color: colors.bgPrimary, border: 'none', borderRadius: radius.md, cursor: 'pointer', fontSize: fontSize.lg, fontWeight: 700, transition: 'opacity 150ms ease' }}
          onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.85')}
          onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          aria-label="Reconnect to server"
        >
          Reconnect
        </button>
      )}
    </div>
  );
}
