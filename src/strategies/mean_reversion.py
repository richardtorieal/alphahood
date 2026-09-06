"""
Mean Reversion Strategy
"""
from typing import Optional, Dict, Any
from .base import BaseStrategy, Signal, ExitSignal
from ..config import get_strategy_param

class MeanReversionStrategy(BaseStrategy):
    """
    Mean Reversion Strategy:
    - Bollinger Band(20,2) squeeze detection + RSI(14) < 30
    - Entry: Limit order at lower Bollinger Band
    - Exit: Mean reversion to 20-day SMA, or -5% hard stop
    - Quality filter: only stocks with market cap > $10B
    - Works with equity positions
    """
    def __init__(self) -> None:
        self.bb_period = get_strategy_param('mean_reversion', 'bb_period', 20)
        self.bb_std_dev = get_strategy_param('mean_reversion', 'bb_std_dev', 2)
        self.rsi_period = get_strategy_param('mean_reversion', 'rsi_period', 14)
        self.rsi_threshold = get_strategy_param('mean_reversion', 'rsi_threshold', 30)
        self.hard_stop_pct = get_strategy_param('mean_reversion', 'hard_stop_pct', -0.05)
        self.min_market_cap = get_strategy_param('mean_reversion', 'min_market_cap', 10000000000)

    def generate_signals(self, symbols: list[str], market_data: Dict[str, Any]) -> list[Signal]:
        signals = []
        for symbol in symbols:
            data = market_data.get(symbol)
            if not data:
                continue

            market_cap = data.get('market_cap', 0)
            if market_cap < self.min_market_cap:
                continue

            rsi = data.get('rsi', 50)
            price = data.get('price', 0)
            bb_lower = data.get('bollinger_lower', data.get('bb_lower', 0))
            bb_upper = data.get('bollinger_upper', data.get('bb_upper', 0))
            sma_20 = data.get('sma_20', 0)
            
            # Squeeze detection: bandwidth is narrow
            bandwidth = (bb_upper - bb_lower) / sma_20 if sma_20 > 0 else 1
            is_squeeze = bandwidth < 0.10 # Assuming 10% is considered a squeeze

            if rsi < self.rsi_threshold and is_squeeze and price <= bb_lower * 1.01:
                signals.append(Signal(
                    symbol=symbol,
                    direction="LONG",
                    strategy_name="mean_reversion",
                    confidence=0.75,
                    entry_price=bb_lower,
                    stop_loss=bb_lower * (1 + self.hard_stop_pct),
                    take_profit=sma_20,
                    order_type="LIMIT",
                    asset_type="EQUITY"
                ))
        return signals

    def should_exit(self, position: Any, market_data: Dict[str, Any]) -> Optional[ExitSignal]:
        data = market_data.get(position.symbol)
        if not data:
            return None
            
        current_price = data.get('price', 0)
        sma_20 = data.get('sma_20', float('inf'))
        
        if current_price <= position.stop_loss:
            return ExitSignal(symbol=position.symbol, reason="Hard Stop Hit", urgency="IMMEDIATE")
        elif current_price >= sma_20:
            return ExitSignal(symbol=position.symbol, reason="Mean Reversion Target Hit", urgency="NORMAL")
            
        return None
