import type { ThemeColors } from '../context/ThemeContext';

// Consistent spacing
export const spacing = {
  xs: '4px',
  sm: '8px',
  md: '12px',
  lg: '16px',
  xl: '20px',
  xxl: '24px',
  xxxl: '32px',
};

// Consistent border radius
export const radius = {
  sm: '4px',
  md: '8px',
  lg: '12px',
};

// Consistent font sizes
export const fontSize = {
  xs: '10px',
  sm: '11px',
  md: '12px',
  lg: '13px',
  xl: '14px',
  xxl: '16px',
  h3: '20px',
  h2: '28px',
  h1: '36px',
};

// Card styles
export const cardStyle = (colors: ThemeColors): React.CSSProperties => ({
  backgroundColor: colors.bgSecondary,
  border: `1px solid ${colors.border}`,
  borderRadius: radius.lg,
  padding: spacing.xl,
});

// Section title style
export const sectionTitle = (colors: ThemeColors): React.CSSProperties => ({
  fontSize: fontSize.lg,
  fontWeight: 700,
  color: colors.textLabel,
  marginBottom: spacing.lg,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  margin: 0,
});

// Label style (small uppercase labels)
export const labelStyle = (colors: ThemeColors): React.CSSProperties => ({
  fontSize: fontSize.xs,
  fontWeight: 700,
  color: colors.textLabel,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
});

// Value style (large mono numbers)
export const valueStyle = (colors: ThemeColors, color?: string): React.CSSProperties => ({
  fontSize: fontSize.h2,
  fontWeight: 800,
  fontFamily: 'var(--font-mono)',
  color: color || colors.textPrimary,
});

// Inner card/box style
export const innerCard = (colors: ThemeColors): React.CSSProperties => ({
  backgroundColor: colors.bgTertiary,
  borderRadius: radius.md,
  padding: spacing.lg,
  border: `1px solid ${colors.border}`,
});

// Stat box style
export const statBox = (colors: ThemeColors, highlight = false): React.CSSProperties => ({
  padding: spacing.lg,
  backgroundColor: colors.bgTertiary,
  borderRadius: radius.md,
  textAlign: 'center',
  border: highlight ? `2px solid ${colors.textPrimary}` : `1px solid ${colors.border}`,
});

// Badge style
export const badge = (color: string, bgColor: string): React.CSSProperties => ({
  padding: '4px 10px',
  borderRadius: radius.sm,
  backgroundColor: bgColor,
  color: color,
  fontSize: fontSize.xs,
  fontWeight: 700,
  fontFamily: 'var(--font-mono)',
  border: `1px solid ${color}40`,
});

// Status dot
export const statusDot = (color: string): React.CSSProperties => ({
  width: '8px',
  height: '8px',
  borderRadius: '50%',
  backgroundColor: color,
});

// Empty state style
export const emptyState = (colors: ThemeColors): React.CSSProperties => ({
  padding: '48px',
  textAlign: 'center',
  color: colors.textMuted,
  backgroundColor: colors.bgTertiary,
  borderRadius: radius.md,
  border: `1px solid ${colors.border}`,
});

// Table header style
export const tableHeader = (colors: ThemeColors): React.CSSProperties => ({
  textAlign: 'left',
  padding: '14px 12px',
  color: colors.textLabel,
  fontWeight: 700,
  fontSize: fontSize.xs,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
});

// Table cell style
export const tableCell = (colors: ThemeColors): React.CSSProperties => ({
  padding: '16px 12px',
  color: colors.textPrimary,
});

// Progress bar container
export const progressBar = (colors: ThemeColors): React.CSSProperties => ({
  height: '8px',
  backgroundColor: colors.bgTertiary,
  borderRadius: radius.sm,
  overflow: 'hidden',
});

// Mono text style
export const monoText = (size: keyof typeof fontSize = 'md'): React.CSSProperties => ({
  fontFamily: 'var(--font-mono)',
  fontSize: fontSize[size],
  fontWeight: 600,
});
