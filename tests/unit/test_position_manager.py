"""
Unit tests for the Position Manager.

Tests:
- Position tracking (Requirement 7.1)
- PnL calculation (Requirement 7.2)
- WebSocket broadcast timing (Requirement 7.3)
- Open position count (Requirement 7.4)
- Close status determination (Requirement 13.5)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.enums import TradeAction
from src.execution.config import ExecutionConfig
from src.execution.position_manager import PositionManager, Position
from src.execution.websocket_broadcaster import MockWebSocketBroadcaster
from src.execution.trade_persistence import TradePersistence


# --- Fixtures ---

@pytest.fixture
def now():
    """Current timestamp for tests."""
    return datetime.now(timezone.utc)


@pytest.fixture
def mock_broadcaster():
    """Create a mock WebSocket broadcaster."""
    return MockWebSocketBroadcaster()


@pytest.fixture
def mock_persistence():
    """Create a mock trade persistence."""
    persistence = MagicMock(spec=TradePersistence)
    persistence.update_trade_record = AsyncMock()
    return persistence


@pytest.fixture
def mock_risk_manager():
    """Create a mock risk manager."""
    risk_manager = MagicMock()
    risk_manager.record_trade_result = MagicMock()
    return risk_manager


@pytest.fixture
def position_manager(mock_broadcaster, mock_persistence, mock_risk_manager):
    """Create a position manager with mocked dependencies."""
    return PositionManager(
        websocket_broadcaster=mock_broadcaster,
        trade_persistence=mock_persistence,
        risk_manager=mock_risk_manager,
    )


# --- Position Tracking Tests ---

class TestPositionTracking:
    """Tests for position tracking (Requirement 7.1)."""

    @pytest.mark.asyncio
    async def test_open_position(self, position_manager, now):
        """Test opening a new position."""
        position = await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        assert position.trade_id == "trade-001"
        assert position.symbol == "AAPL"
        assert position.entry_price == 150.0
        assert position.stop_loss == 145.0
        assert position.take_profit == 165.0
        assert position.position_size == 100.0
        assert position.action == TradeAction.BUY
        assert position.status == "open"

    @pytest.mark.asyncio
    async def test_get_position(self, position_manager, now):
        """Test retrieving a position by trade ID."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = position_manager.get_position("trade-001")
        
        assert position is not None
        assert position.trade_id == "trade-001"

    @pytest.mark.asyncio
    async def test_get_position_by_symbol(self, position_manager, now):
        """Test retrieving a position by symbol."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = position_manager.get_position_by_symbol("AAPL")
        
        assert position is not None
        assert position.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_get_nonexistent_position(self, position_manager):
        """Test retrieving a nonexistent position returns None."""
        position = position_manager.get_position("nonexistent")
        
        assert position is None

    @pytest.mark.asyncio
    async def test_get_all_open_positions(self, position_manager, now):
        """Test retrieving all open positions."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        await position_manager.open_position(
            trade_id="trade-002",
            symbol="MSFT",
            entry_price=300.0,
            stop_loss=290.0,
            take_profit=320.0,
            position_size=50.0,
            action=TradeAction.BUY,
            exness_order_id="order-002",
            opened_at=now,
        )
        
        positions = position_manager.get_open_positions()
        
        assert len(positions) == 2


# --- Open Position Count Tests ---

class TestOpenPositionCount:
    """Tests for open position count (Requirement 7.4)."""

    @pytest.mark.asyncio
    async def test_initial_count_is_zero(self, position_manager):
        """Test initial position count is zero."""
        assert position_manager.open_position_count == 0

    @pytest.mark.asyncio
    async def test_count_increases_on_open(self, position_manager, now):
        """Test count increases when position is opened."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        assert position_manager.open_position_count == 1

    @pytest.mark.asyncio
    async def test_count_decreases_on_close(self, position_manager, now):
        """Test count decreases when position is closed."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        assert position_manager.open_position_count == 1
        
        await position_manager.close_position(
            trade_id="trade-001",
            exit_price=160.0,
            close_reason="manual",
        )
        
        assert position_manager.open_position_count == 0

    @pytest.mark.asyncio
    async def test_count_accurate_with_multiple_positions(self, position_manager, now):
        """Test count is accurate with multiple positions."""
        for i in range(5):
            await position_manager.open_position(
                trade_id=f"trade-{i:03d}",
                symbol=f"SYM{i}",
                entry_price=100.0 + i,
                stop_loss=95.0 + i,
                take_profit=110.0 + i,
                position_size=100.0,
                action=TradeAction.BUY,
                exness_order_id=f"order-{i:03d}",
                opened_at=now,
            )
        
        assert position_manager.open_position_count == 5
        
        # Close 2 positions
        await position_manager.close_position("trade-000", 105.0)
        await position_manager.close_position("trade-002", 107.0)
        
        assert position_manager.open_position_count == 3


# --- PnL Calculation Tests ---

class TestPnLCalculation:
    """Tests for PnL calculation (Requirement 7.2)."""

    @pytest.mark.asyncio
    async def test_buy_profit_calculation(self, position_manager, now):
        """Test PnL calculation for profitable BUY trade."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=160.0,  # $10 profit per share
            close_reason="manual",
        )
        
        # PnL = (160 - 150) * 100 = 1000
        assert position.pnl == 1000.0
        # PnL% = (10 / 150) * 100 = 6.67%
        assert abs(position.pnl_pct - 6.67) < 0.1

    @pytest.mark.asyncio
    async def test_buy_loss_calculation(self, position_manager, now):
        """Test PnL calculation for losing BUY trade."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=145.0,  # $5 loss per share
            close_reason="sl",
        )
        
        # PnL = (145 - 150) * 100 = -500
        assert position.pnl == -500.0
        # PnL% = (-5 / 150) * 100 = -3.33%
        assert abs(position.pnl_pct - (-3.33)) < 0.1

    @pytest.mark.asyncio
    async def test_sell_profit_calculation(self, position_manager, now):
        """Test PnL calculation for profitable SELL trade."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=155.0,
            take_profit=140.0,
            position_size=100.0,
            action=TradeAction.SELL,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=140.0,  # $10 profit per share for SELL
            close_reason="tp",
        )
        
        # PnL = (150 - 140) * 100 = 1000
        assert position.pnl == 1000.0

    @pytest.mark.asyncio
    async def test_sell_loss_calculation(self, position_manager, now):
        """Test PnL calculation for losing SELL trade."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=155.0,
            take_profit=140.0,
            position_size=100.0,
            action=TradeAction.SELL,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=155.0,  # $5 loss per share for SELL
            close_reason="sl",
        )
        
        # PnL = (150 - 155) * 100 = -500
        assert position.pnl == -500.0

    @pytest.mark.asyncio
    async def test_close_records_exit_details(self, position_manager, now):
        """Test that close records all exit details (Requirement 7.2)."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        close_time = datetime.now(timezone.utc)
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=160.0,
            close_reason="manual",
            closed_at=close_time,
        )
        
        assert position.exit_price == 160.0
        assert position.pnl is not None
        assert position.pnl_pct is not None
        assert position.closed_at == close_time


# --- Close Status Tests ---

class TestCloseStatus:
    """Tests for close status determination (Requirement 13.5)."""

    @pytest.mark.asyncio
    async def test_closed_profit_status(self, position_manager, now):
        """Test closed_profit status for profitable manual close."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=160.0,  # Profit
            close_reason="manual",
        )
        
        assert position.status == "closed_profit"

    @pytest.mark.asyncio
    async def test_closed_loss_status(self, position_manager, now):
        """Test closed_loss status for losing manual close."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=148.0,  # Loss
            close_reason="manual",
        )
        
        assert position.status == "closed_loss"

    @pytest.mark.asyncio
    async def test_closed_sl_status(self, position_manager, now):
        """Test closed_sl status for stop-loss close."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=145.0,
            close_reason="sl",
        )
        
        assert position.status == "closed_sl"

    @pytest.mark.asyncio
    async def test_closed_tp_status(self, position_manager, now):
        """Test closed_tp status for take-profit close."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.close_position(
            trade_id="trade-001",
            exit_price=165.0,
            close_reason="tp",
        )
        
        assert position.status == "closed_tp"


# --- WebSocket Broadcast Tests ---

class TestWebSocketBroadcast:
    """Tests for WebSocket broadcast (Requirement 7.3)."""

    @pytest.mark.asyncio
    async def test_broadcast_on_open(self, position_manager, mock_broadcaster, now):
        """Test broadcast is sent when position is opened."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        broadcasts = mock_broadcaster.get_broadcasts_of_type("position_update")
        assert len(broadcasts) == 1
        assert broadcasts[0]["update_type"] == "opened"
        assert broadcasts[0]["data"]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_broadcast_on_close(self, position_manager, mock_broadcaster, now):
        """Test broadcast is sent when position is closed."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        mock_broadcaster.clear_broadcasts()
        
        await position_manager.close_position(
            trade_id="trade-001",
            exit_price=160.0,
            close_reason="manual",
        )
        
        broadcasts = mock_broadcaster.get_broadcasts_of_type("position_update")
        assert len(broadcasts) == 1
        assert broadcasts[0]["update_type"] == "closed"
        assert broadcasts[0]["data"]["exit_price"] == 160.0
        assert broadcasts[0]["data"]["pnl"] is not None

    @pytest.mark.asyncio
    async def test_broadcast_on_modify(self, position_manager, mock_broadcaster, now):
        """Test broadcast is sent when position is modified."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        mock_broadcaster.clear_broadcasts()
        
        await position_manager.modify_position(
            trade_id="trade-001",
            stop_loss=146.0,
        )
        
        broadcasts = mock_broadcaster.get_broadcasts_of_type("position_update")
        assert len(broadcasts) == 1
        assert broadcasts[0]["update_type"] == "modified"

    @pytest.mark.asyncio
    async def test_broadcast_timeout_handling(self, now):
        """Test that broadcast timeout is handled gracefully."""
        # Create a slow broadcaster
        slow_broadcaster = MockWebSocketBroadcaster()
        
        async def slow_broadcast(message):
            await asyncio.sleep(2.0)  # Longer than 1 second timeout
            slow_broadcaster.broadcasts.append(message)
        
        slow_broadcaster._broadcast = slow_broadcast
        
        config = ExecutionConfig()
        config.position_manager.max_broadcast_delay_seconds = 0.1  # Short timeout
        
        manager = PositionManager(
            config=config,
            websocket_broadcaster=slow_broadcaster,
        )
        
        # Should not raise, just log warning
        await manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        # Position should still be tracked
        assert manager.open_position_count == 1


# --- Position Modification Tests ---

class TestPositionModification:
    """Tests for position modification."""

    @pytest.mark.asyncio
    async def test_modify_stop_loss(self, position_manager, now):
        """Test modifying stop-loss."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.modify_position(
            trade_id="trade-001",
            stop_loss=146.0,
        )
        
        assert position.stop_loss == 146.0
        assert position.take_profit == 165.0  # Unchanged

    @pytest.mark.asyncio
    async def test_modify_take_profit(self, position_manager, now):
        """Test modifying take-profit."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        position = await position_manager.modify_position(
            trade_id="trade-001",
            take_profit=170.0,
        )
        
        assert position.stop_loss == 145.0  # Unchanged
        assert position.take_profit == 170.0

    @pytest.mark.asyncio
    async def test_modify_nonexistent_position(self, position_manager):
        """Test modifying nonexistent position raises error."""
        with pytest.raises(ValueError) as exc_info:
            await position_manager.modify_position(
                trade_id="nonexistent",
                stop_loss=146.0,
            )
        
        assert "not found" in str(exc_info.value).lower()


# --- Persistence Integration Tests ---

class TestPersistenceIntegration:
    """Tests for persistence integration."""

    @pytest.mark.asyncio
    async def test_close_updates_persistence(self, position_manager, mock_persistence, now):
        """Test that close updates trade record in persistence."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        await position_manager.close_position(
            trade_id="trade-001",
            exit_price=160.0,
            close_reason="manual",
        )
        
        mock_persistence.update_trade_record.assert_called_once()
        call_args = mock_persistence.update_trade_record.call_args
        assert call_args.kwargs["trade_id"] == "trade-001"
        assert call_args.kwargs["exit_price"] == 160.0
        assert call_args.kwargs["status"] == "closed_profit"


# --- Risk Manager Integration Tests ---

class TestRiskManagerIntegration:
    """Tests for risk manager integration."""

    @pytest.mark.asyncio
    async def test_close_records_trade_result(self, position_manager, mock_risk_manager, now):
        """Test that close records trade result in risk manager."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        await position_manager.close_position(
            trade_id="trade-001",
            exit_price=160.0,
            close_reason="manual",
        )
        
        mock_risk_manager.record_trade_result.assert_called_once()
        # PnL should be 1000 (10 * 100)
        call_args = mock_risk_manager.record_trade_result.call_args
        assert call_args[0][0] == 1000.0


# --- Summary Tests ---

class TestPositionsSummary:
    """Tests for positions summary."""

    @pytest.mark.asyncio
    async def test_get_positions_summary(self, position_manager, now):
        """Test getting positions summary."""
        await position_manager.open_position(
            trade_id="trade-001",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-001",
            opened_at=now,
        )
        
        await position_manager.open_position(
            trade_id="trade-002",
            symbol="AAPL",
            entry_price=151.0,
            stop_loss=146.0,
            take_profit=166.0,
            position_size=50.0,
            action=TradeAction.BUY,
            exness_order_id="order-002",
            opened_at=now,
        )
        
        summary = position_manager.get_positions_summary()
        
        assert summary["open_count"] == 2
        assert summary["total_exposure"] == 150.0
        assert "AAPL" in summary["by_symbol"]
        assert len(summary["by_symbol"]["AAPL"]) == 2
