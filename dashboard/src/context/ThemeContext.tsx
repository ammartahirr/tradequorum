import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

export type Theme = 'dark' | 'light';

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
  colors: ThemeColors;
}

export interface ThemeColors {
  // Backgrounds
  bgPrimary: string;
  bgSecondary: string;
  bgTertiary: string;
  bgHover: string;
  bgCard: string;
  // Text
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  textLabel: string;
  // Borders
  border: string;
  borderLight: string;
  borderDark: string;
  // Accents
  accent: string;
  accentHover: string;
  // Status colors
  success: string;
  successBg: string;
  successLight: string;
  warning: string;
  warningBg: string;
  warningLight: string;
  error: string;
  errorBg: string;
  errorLight: string;
  info: string;
  infoBg: string;
  infoLight: string;
  // Special
  highlight: string;
  shadow: string;
}

const darkTheme: ThemeColors = {
  bgPrimary: '#000000',
  bgSecondary: '#0a0a0a',
  bgTertiary: '#141414',
  bgHover: '#1a1a1a',
  bgCard: '#0d0d0d',
  textPrimary: '#ffffff',
  textSecondary: '#b3b3b3',
  textMuted: '#666666',
  textLabel: '#888888',
  border: '#262626',
  borderLight: '#1a1a1a',
  borderDark: '#333333',
  accent: '#ffffff',
  accentHover: '#e5e5e5',
  success: '#00d26a',
  successBg: 'rgba(0, 210, 106, 0.12)',
  successLight: '#00ff80',
  warning: '#ffb800',
  warningBg: 'rgba(255, 184, 0, 0.12)',
  warningLight: '#ffd000',
  error: '#ff3b3b',
  errorBg: 'rgba(255, 59, 59, 0.12)',
  errorLight: '#ff5555',
  info: '#0095ff',
  infoBg: 'rgba(0, 149, 255, 0.12)',
  infoLight: '#33aaff',
  highlight: '#ffffff',
  shadow: 'rgba(0, 0, 0, 0.5)',
};

const lightTheme: ThemeColors = {
  bgPrimary: '#ffffff',
  bgSecondary: '#fafafa',
  bgTertiary: '#f0f0f0',
  bgHover: '#e8e8e8',
  bgCard: '#ffffff',
  textPrimary: '#000000',
  textSecondary: '#1a1a1a',
  textMuted: '#404040',
  textLabel: '#000000',
  border: '#d0d0d0',
  borderLight: '#e5e5e5',
  borderDark: '#000000',
  accent: '#000000',
  accentHover: '#1a1a1a',
  success: '#00a854',
  successBg: 'rgba(0, 168, 84, 0.1)',
  successLight: '#00c964',
  warning: '#d48800',
  warningBg: 'rgba(212, 136, 0, 0.1)',
  warningLight: '#f5a000',
  error: '#d32f2f',
  errorBg: 'rgba(211, 47, 47, 0.1)',
  errorLight: '#ef5350',
  info: '#0066cc',
  infoBg: 'rgba(0, 102, 204, 0.1)',
  infoLight: '#1976d2',
  highlight: '#000000',
  shadow: 'rgba(0, 0, 0, 0.15)',
};

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('theme');
    return (saved as Theme) || 'dark';
  });

  useEffect(() => {
    localStorage.setItem('theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  const colors = theme === 'dark' ? darkTheme : lightTheme;

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, colors }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
