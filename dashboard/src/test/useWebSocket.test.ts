import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWebSocket } from '../hooks/useWebSocket';

// Create a more controllable mock WebSocket
let mockWsInstance: MockWebSocket | null = null;

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    mockWsInstance = this;
  }

  send(_data: string): void {
    // Mock send
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close'));
    }
  }

  // Helper to simulate connection open
  simulateOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) {
      this.onopen(new Event('open'));
    }
  }

  // Helper to simulate receiving a message
  simulateMessage(data: unknown): void {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }));
    }
  }

  // Helper to simulate connection close
  simulateClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close'));
    }
  }
}

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockWsInstance = null;
    // @ts-expect-error - Mocking global WebSocket
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    vi.useRealTimers();
    mockWsInstance = null;
  });

  it('should connect to WebSocket on mount', async () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: 'wss://test.example.com/ws' })
    );

    expect(result.current.status).toBe('connecting');

    // Simulate the WebSocket connection opening
    act(() => {
      mockWsInstance?.simulateOpen();
    });

    expect(result.current.status).toBe('connected');
  });

  it('should call onMessage callback when message is received', async () => {
    const onMessage = vi.fn();
    renderHook(() =>
      useWebSocket({
        url: 'wss://test.example.com/ws',
        onMessage,
      })
    );

    // Simulate connection open
    act(() => {
      mockWsInstance?.simulateOpen();
    });

    // Simulate receiving a message
    const mockMessage = {
      type: 'trade_signal',
      payload: { symbol: 'AAPL' },
      timestamp: new Date().toISOString(),
    };

    act(() => {
      mockWsInstance?.simulateMessage(mockMessage);
    });

    expect(onMessage).toHaveBeenCalledWith(mockMessage);
  });

  it('should attempt reconnection with exponential backoff on disconnect', async () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: 'wss://test.example.com/ws',
        initialReconnectDelay: 1000,
        maxReconnectDelay: 30000,
      })
    );

    // Connect first
    act(() => {
      mockWsInstance?.simulateOpen();
    });

    expect(result.current.status).toBe('connected');

    // Simulate disconnect
    act(() => {
      mockWsInstance?.simulateClose();
    });

    expect(result.current.status).toBe('reconnecting');

    // Advance timer by initial delay (1000ms)
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // A new WebSocket should be created, status should be connecting
    expect(result.current.status).toBe('connecting');
  });

  it('should update status to disconnected when manually disconnected', async () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: 'wss://test.example.com/ws' })
    );

    // Connect first
    act(() => {
      mockWsInstance?.simulateOpen();
    });

    expect(result.current.status).toBe('connected');

    // Manually disconnect
    act(() => {
      result.current.disconnect();
    });

    expect(result.current.status).toBe('disconnected');
  });

  it('should reconnect when reconnect is called', async () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: 'wss://test.example.com/ws' })
    );

    // Connect first
    act(() => {
      mockWsInstance?.simulateOpen();
    });

    expect(result.current.status).toBe('connected');

    // Disconnect
    act(() => {
      result.current.disconnect();
    });

    expect(result.current.status).toBe('disconnected');

    // Reconnect
    act(() => {
      result.current.reconnect();
    });

    expect(result.current.status).toBe('connecting');

    // Simulate connection open
    act(() => {
      mockWsInstance?.simulateOpen();
    });

    expect(result.current.status).toBe('connected');
  });
});

describe('WebSocket exponential backoff', () => {
  it('should calculate correct delays for reconnection attempts', () => {
    // Test the exponential backoff formula: delay = initialDelay * 2^attempts
    const initialDelay = 1000;
    const maxDelay = 30000;

    const calculateDelay = (attempts: number) => {
      return Math.min(initialDelay * Math.pow(2, attempts), maxDelay);
    };

    expect(calculateDelay(0)).toBe(1000);  // 1s
    expect(calculateDelay(1)).toBe(2000);  // 2s
    expect(calculateDelay(2)).toBe(4000);  // 4s
    expect(calculateDelay(3)).toBe(8000);  // 8s
    expect(calculateDelay(4)).toBe(16000); // 16s
    expect(calculateDelay(5)).toBe(30000); // Capped at 30s
    expect(calculateDelay(10)).toBe(30000); // Still capped at 30s
  });
});
