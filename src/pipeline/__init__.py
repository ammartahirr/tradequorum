"""Trading pipeline module for wiring all components together."""

from .pipeline_config import PipelineConfig, DEFAULT_PIPELINE_CONFIG

__all__ = ["PipelineConfig", "DEFAULT_PIPELINE_CONFIG"]

# Lazy import to avoid circular dependencies
def get_trading_pipeline():
    from .trading_pipeline import TradingPipeline, PipelineResult
    return TradingPipeline, PipelineResult
