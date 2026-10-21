"""
Configuration for the Trading Pipeline.

Centralizes all configuration for the integrated trading system.
"""

from dataclasses import dataclass, field
from typing import Optional

from src.agents.technical.config import TechnicalAgentConfig
from src.agents.strategy.config import StrategyConfig
from src.agents.risk.config import RiskConfig
from src.execution.config import ExecutionConfig


@dataclass
class PipelineConfig:
    """Complete configuration for the trading pipeline."""
    
    # Agent configurations
    technical_config: TechnicalAgentConfig = field(default_factory=TechnicalAgentConfig)
    strategy_config: StrategyConfig = field(default_factory=StrategyConfig)
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    
    # Execution configuration
    execution_config: ExecutionConfig = field(default_factory=ExecutionConfig)
    
    # Pipeline settings
    enable_websocket_broadcasts: bool = True
    enable_persistence: bool = True
    use_sagemaker: bool = True
    use_llm: bool = True
    
    # AWS settings
    aws_region: str = "us-east-1"
    signals_table: str = "trading-signals"
    decisions_table: str = "trading-decisions"
    trades_table: str = "trading-trades"


# Default pipeline configuration
DEFAULT_PIPELINE_CONFIG = PipelineConfig()
