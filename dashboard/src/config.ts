/**
 * Runtime endpoints. VITE_API_URL / VITE_WS_URL may be absolute
 * (https://api.example.com/api, wss://api.example.com/ws) or relative to the
 * page (/api, /ws) when the dashboard is served behind the same nginx.
 */
function resolveWsUrl(raw: string | undefined): string {
  const value = raw || '/ws';
  if (/^wss?:\/\//.test(value)) return value;
  if (typeof window === 'undefined') return `ws://localhost${value}`;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${value.startsWith('/') ? '' : '/'}${value}`;
}

export const API_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');
export const WS_URL = resolveWsUrl(import.meta.env.VITE_WS_URL || import.meta.env.VITE_WEBSOCKET_URL);
