import { Suspense, lazy, useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider, useTheme } from './context/ThemeContext';
import { TradingProvider, useTradingContext } from './context/TradingContext';
import { Dashboard } from './components/Dashboard';
import { Header } from './components/Header';
import { WS_URL } from './config';
import { fontSize, radius, spacing } from './styles/shared';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchOnWindowFocus: false,
    },
  },
});

// Chart library is only loaded when the sandbox is opened
const SandboxPage = lazy(() =>
  import('./components/sandbox/SandboxPage').then((m) => ({ default: m.SandboxPage })),
);

type View = 'live' | 'sandbox';

const viewFromHash = (): View => (window.location.hash === '#/sandbox' ? 'sandbox' : 'live');

function NavTabs({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const { colors } = useTheme();
  const tab = (v: View, label: string) => (
    <button
      key={v}
      onClick={() => onChange(v)}
      aria-current={view === v ? 'page' : undefined}
      style={{
        padding: `${spacing.sm} ${spacing.lg}`,
        borderRadius: radius.md,
        border: `1px solid ${view === v ? colors.textPrimary : colors.border}`,
        backgroundColor: view === v ? colors.textPrimary : 'transparent',
        color: view === v ? colors.bgPrimary : colors.textSecondary,
        fontWeight: 700,
        fontSize: fontSize.lg,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  );
  return (
    <nav style={{ display: 'flex', gap: spacing.sm }}>
      {tab('live', 'Live')}
      {tab('sandbox', 'Sandbox')}
    </nav>
  );
}

function Shell() {
  const [view, setView] = useState<View>(viewFromHash);
  const { state, reconnect } = useTradingContext();
  const { colors } = useTheme();

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const change = (v: View) => {
    window.location.hash = v === 'sandbox' ? '#/sandbox' : '#/';
    setView(v);
  };
  const nav = <NavTabs view={view} onChange={change} />;

  if (view === 'live') return <Dashboard nav={nav} />;
  return (
    <div style={{ minHeight: '100vh', backgroundColor: colors.bgPrimary, color: colors.textPrimary }}>
      <Header
        connectionStatus={state.connectionStatus}
        onReconnect={reconnect}
        lastUpdateTime={state.lastUpdateTime}
        nav={nav}
      />
      <Suspense fallback={<div style={{ padding: spacing.xxl, color: colors.textMuted }}>Loading sandbox…</div>}>
        <SandboxPage />
      </Suspense>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TradingProvider websocketUrl={WS_URL}>
          <Shell />
        </TradingProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
