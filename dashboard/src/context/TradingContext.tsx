import React, { createContext, useContext, useCallback, useReducer, useRef, useEffect } from 'react';
import type {
  Position,
  TradeRecord,
  TradeSignal,
  AgentStatus,
  PerformanceMetrics,
  WebSocketMessage,
} from '../types/trading';
import { useWebSocket, type ConnectionStatus } from '../hooks/useWebSocket';

// State interface
interface TradingState {
  positions: Position[];
  tradeHistory: TradeRecord[];
  tradeSignals: TradeSignal[];
  agentStatuses: AgentStatus[];
  performanceMetrics: PerformanceMetrics | null;
  connectionStatus: ConnectionStatus;
  lastUpdateTime: number | null;
}

// Action types
type TradingAction =
  | { type: 'SET_POSITIONS'; payload: Position[] }
  | { type: 'UPDATE_POSITION'; payload: Position }
  | { type: 'ADD_TRADE_RECORD'; payload: TradeRecord }
  | { type: 'SET_TRADE_HISTORY'; payload: TradeRecord[] }
  | { type: 'ADD_TRADE_SIGNAL'; payload: TradeSignal }
  | { type: 'SET_TRADE_SIGNALS'; payload: TradeSignal[] }
  | { type: 'UPDATE_AGENT_STATUS'; payload: AgentStatus }
  | { type: 'SET_AGENT_STATUSES'; payload: AgentStatus[] }
  | { type: 'SET_PERFORMANCE_METRICS'; payload: PerformanceMetrics }
  | { type: 'SET_CONNECTION_STATUS'; payload: ConnectionStatus }
  | { type: 'SET_LAST_UPDATE_TIME'; payload: number };

// Initial state
const initialState: TradingState = {
  positions: [],
  tradeHistory: [],
  tradeSignals: [],
  agentStatuses: [],
  performanceMetrics: null,
  connectionStatus: 'disconnected',
  lastUpdateTime: null,
};

// Reducer
function tradingReducer(state: TradingState, action: TradingAction): TradingState {
  switch (action.type) {
    case 'SET_POSITIONS':
      return { ...state, positions: action.payload };
    
    case 'UPDATE_POSITION': {
      const existingIndex = state.positions.findIndex(
        (p) => p.tradeId === action.payload.tradeId
      );
      if (existingIndex >= 0) {
        const newPositions = [...state.positions];
        newPositions[existingIndex] = action.payload;
        return { ...state, positions: newPositions };
      }
      return { ...state, positions: [...state.positions, action.payload] };
    }
    
    case 'ADD_TRADE_RECORD':
      return {
        ...state,
        tradeHistory: [action.payload, ...state.tradeHistory].slice(0, 100), // Keep last 100
      };
    
    case 'SET_TRADE_HISTORY':
      return { ...state, tradeHistory: action.payload };
    
    case 'ADD_TRADE_SIGNAL':
      return {
        ...state,
        tradeSignals: [action.payload, ...state.tradeSignals].slice(0, 50), // Keep last 50
      };
    
    case 'SET_TRADE_SIGNALS':
      return { ...state, tradeSignals: action.payload };
    
    case 'UPDATE_AGENT_STATUS': {
      const existingIndex = state.agentStatuses.findIndex(
        (a) => a.agentType === action.payload.agentType
      );
      if (existingIndex >= 0) {
        const newStatuses = [...state.agentStatuses];
        newStatuses[existingIndex] = action.payload;
        return { ...state, agentStatuses: newStatuses };
      }
      return { ...state, agentStatuses: [...state.agentStatuses, action.payload] };
    }
    
    case 'SET_AGENT_STATUSES':
      return { ...state, agentStatuses: action.payload };
    
    case 'SET_PERFORMANCE_METRICS':
      return { ...state, performanceMetrics: action.payload };
    
    case 'SET_CONNECTION_STATUS':
      return { ...state, connectionStatus: action.payload };
    
    case 'SET_LAST_UPDATE_TIME':
      return { ...state, lastUpdateTime: action.payload };
    
    default:
      return state;
  }
}

// Context interface
interface TradingContextValue {
  state: TradingState;
  dispatch: React.Dispatch<TradingAction>;
  reconnect: () => void;
}

const TradingContext = createContext<TradingContextValue | null>(null);

interface TradingProviderProps {
  children: React.ReactNode;
  websocketUrl: string;
}

/**
 * Trading data provider with WebSocket integration.
 * Implements Requirement 8.2: Update UI components within 500ms of WebSocket message receipt.
 */
export function TradingProvider({ children, websocketUrl }: TradingProviderProps) {
  const [state, dispatch] = useReducer(tradingReducer, initialState);
  const updateTimerRef = useRef<number | null>(null);

  // Track update timing for Requirement 8.2 compliance
  const trackUpdateTime = useCallback(() => {
    const now = performance.now();
    dispatch({ type: 'SET_LAST_UPDATE_TIME', payload: now });
  }, []);

  // Handle incoming WebSocket messages
  const handleMessage = useCallback((message: WebSocketMessage) => {
    // Record message receipt time for timing verification
    const receiptTime = performance.now();
    
    switch (message.type) {
      case 'trade_signal':
        dispatch({ type: 'ADD_TRADE_SIGNAL', payload: message.payload as TradeSignal });
        break;
      
      case 'position_update':
        dispatch({ type: 'UPDATE_POSITION', payload: message.payload as Position });
        break;
      
      case 'trade_executed':
        dispatch({ type: 'ADD_TRADE_RECORD', payload: message.payload as TradeRecord });
        break;
      
      case 'agent_status':
        dispatch({ type: 'UPDATE_AGENT_STATUS', payload: message.payload as AgentStatus });
        break;
      
      case 'performance_update':
        dispatch({ type: 'SET_PERFORMANCE_METRICS', payload: message.payload as PerformanceMetrics });
        break;
      
      default:
        console.warn('Unknown message type:', message.type);
    }

    // Track update completion time
    if (updateTimerRef.current) {
      cancelAnimationFrame(updateTimerRef.current);
    }
    updateTimerRef.current = requestAnimationFrame(() => {
      const updateTime = performance.now() - receiptTime;
      if (updateTime > 500) {
        console.warn(`UI update took ${updateTime.toFixed(2)}ms, exceeding 500ms target`);
      }
      trackUpdateTime();
    });
  }, [trackUpdateTime]);

  const { status, reconnect } = useWebSocket({
    url: websocketUrl,
    onMessage: handleMessage,
  });

  // Update connection status in state
  useEffect(() => {
    dispatch({ type: 'SET_CONNECTION_STATUS', payload: status });
  }, [status]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (updateTimerRef.current) {
        cancelAnimationFrame(updateTimerRef.current);
      }
    };
  }, []);

  const value: TradingContextValue = {
    state,
    dispatch,
    reconnect,
  };

  return (
    <TradingContext.Provider value={value}>
      {children}
    </TradingContext.Provider>
  );
}

export function useTradingContext(): TradingContextValue {
  const context = useContext(TradingContext);
  if (!context) {
    throw new Error('useTradingContext must be used within a TradingProvider');
  }
  return context;
}
