import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './context/ThemeContext';
import { TradingProvider } from './context/TradingContext';
import { Dashboard } from './components/Dashboard';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchOnWindowFocus: false,
    },
  },
});

const WEBSOCKET_URL = import.meta.env.VITE_WEBSOCKET_URL || 'wss://api.example.com/ws';

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TradingProvider websocketUrl={WEBSOCKET_URL}>
          <Dashboard />
        </TradingProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
