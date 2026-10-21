"""WebSocket connection manager for real-time updates."""
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, Set[WebSocket]] = {}  # symbol -> connections
    
    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        # Remove from all subscriptions
        for symbol in list(self.subscriptions.keys()):
            if websocket in self.subscriptions[symbol]:
                self.subscriptions[symbol].remove(websocket)
                if not self.subscriptions[symbol]:
                    del self.subscriptions[symbol]
        
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    def subscribe(self, websocket: WebSocket, symbol: str):
        """Subscribe a connection to a symbol's updates."""
        if symbol not in self.subscriptions:
            self.subscriptions[symbol] = set()
        self.subscriptions[symbol].add(websocket)
    
    def unsubscribe(self, websocket: WebSocket, symbol: str):
        """Unsubscribe a connection from a symbol's updates."""
        if symbol in self.subscriptions and websocket in self.subscriptions[symbol]:
            self.subscriptions[symbol].remove(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return
        
        message_json = json.dumps(message, default=str)
        disconnected = []
        
        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to connection: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected
        for conn in disconnected:
            self.disconnect(conn)
    
    async def broadcast_to_symbol(self, symbol: str, message: dict):
        """Broadcast a message to clients subscribed to a symbol."""
        if symbol not in self.subscriptions:
            return
        
        message_json = json.dumps(message, default=str)
        disconnected = []
        
        for connection in self.subscriptions[symbol]:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to connection: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected
        for conn in disconnected:
            self.disconnect(conn)
    
    async def send_personal(self, websocket: WebSocket, message: dict):
        """Send a message to a specific connection."""
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception as e:
            logger.warning(f"Failed to send personal message: {e}")
            self.disconnect(websocket)


# Global connection manager instance
manager = ConnectionManager()


async def broadcast_trade_update(trade_data: dict):
    """Broadcast a trade update to all clients."""
    await manager.broadcast({
        "type": "trade_update",
        "data": trade_data,
        "timestamp": datetime.utcnow().isoformat(),
    })


async def broadcast_position_update(position_data: dict):
    """Broadcast a position update to all clients."""
    await manager.broadcast({
        "type": "position_update",
        "data": position_data,
        "timestamp": datetime.utcnow().isoformat(),
    })


async def broadcast_signal(signal_type: str, signal_data: dict):
    """Broadcast a new signal to all clients."""
    symbol = signal_data.get("symbol")
    message = {
        "type": f"{signal_type}_signal",
        "data": signal_data,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    # Broadcast to all and to symbol subscribers
    await manager.broadcast(message)


async def broadcast_risk_alert(alert_data: dict):
    """Broadcast a risk alert to all clients."""
    await manager.broadcast({
        "type": "risk_alert",
        "data": alert_data,
        "timestamp": datetime.utcnow().isoformat(),
    })


async def broadcast_decision(decision_data: dict):
    """Broadcast a trade decision to all clients."""
    await manager.broadcast({
        "type": "trade_decision",
        "data": decision_data,
        "timestamp": datetime.utcnow().isoformat(),
    })
