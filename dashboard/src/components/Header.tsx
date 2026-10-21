import { useTheme } from '../context/ThemeContext';
import { useLiveClock } from '../hooks/useLiveClock';
import { ConnectionStatus } from './ConnectionStatus';
import { labelStyle, fontSize, spacing, radius } from '../styles/shared';
import type { ConnectionStatus as ConnectionStatusType } from '../hooks/useWebSocket';

interface HeaderProps {
  connectionStatus: ConnectionStatusType;
  onReconnect: () => void;
  lastUpdateTime: number | null;
}

function ThemeToggle() {
  const { theme, toggleTheme, colors } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '44px', height: '44px', backgroundColor: colors.bgTertiary, border: `1px solid ${colors.border}`, borderRadius: radius.md, cursor: 'pointer', transition: 'all 150ms ease', color: colors.textPrimary }}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      {theme === 'dark' ? (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="5" /><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" /></svg>
      ) : (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /></svg>
      )}
    </button>
  );
}

export function Header({ connectionStatus, onReconnect, lastUpdateTime }: HeaderProps) {
  const { colors } = useTheme();
  const { timeString, dateString } = useLiveClock();
  const isConnected = connectionStatus === 'connected';
  const statusColor = isConnected ? colors.success : colors.error;

  return (
    <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: `${spacing.lg} ${spacing.xxl}`, borderBottom: `1px solid ${colors.border}`, backgroundColor: colors.bgSecondary, position: 'sticky', top: 0, zIndex: 100 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.xl }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.lg }}>
          <div style={{ width: '44px', height: '44px', backgroundColor: colors.textPrimary, borderRadius: radius.md, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={colors.bgPrimary} strokeWidth="2.5"><path d="M3 3v18h18" /><path d="M18 9l-5 5-4-4-3 3" /></svg>
          </div>
          <div>
            <h1 style={{ fontSize: fontSize.h3, fontWeight: 800, margin: 0, letterSpacing: '-0.02em', color: colors.textPrimary }}>AI Trading</h1>
            <span style={{ fontSize: fontSize.sm, color: colors.textMuted, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>Multi-Agent System</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, padding: `${spacing.sm} ${spacing.lg}`, backgroundColor: isConnected ? colors.successBg : colors.errorBg, borderRadius: '20px', fontSize: fontSize.md, fontWeight: 700, color: statusColor, fontFamily: 'var(--font-mono)', border: `1px solid ${statusColor}` }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'currentColor', animation: isConnected ? 'pulse 2s infinite' : 'none' }} />
          {isConnected ? 'LIVE' : 'OFFLINE'}
        </div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: fontSize.h2, fontWeight: 800, fontFamily: 'var(--font-mono)', color: colors.textPrimary, letterSpacing: '-0.02em' }}>{timeString}</div>
        <div style={{ fontSize: fontSize.md, color: colors.textMuted, fontWeight: 600 }}>{dateString}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.lg }}>
        {lastUpdateTime && (
          <div style={{ textAlign: 'right' }}>
            <div style={{ ...labelStyle(colors), marginBottom: spacing.xs }}>Last Update</div>
            <div style={{ fontSize: fontSize.lg, color: colors.textSecondary, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{new Date(lastUpdateTime).toLocaleTimeString()}</div>
          </div>
        )}
        <ConnectionStatus status={connectionStatus} onReconnect={onReconnect} />
        <ThemeToggle />
      </div>
    </header>
  );
}
