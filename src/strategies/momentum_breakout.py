"""
Momentum Breakout Strategy
"""
from typing import Optional, Dict, Any
from .base import BaseStrategy, Signal, ExitSignal, OptionDetails
from ..config import get_strategy_param

class MomentumBreakoutStrategy(BaseStrategy):
    """
    Momentum Breakout Strategy:
    - Uses RSI > 60, price crossing above 20-day SMA, volume > 1.5x 20-day avg volume
    - Entry: Market order on breakout confirmation
    - Exit: Trailing stop at 2x ATR(14), hard stop at -3%
    """
    def __init__(self) -> None:
        self.rsi_threshold = get_strategy_param('momentum_breakout', 'rsi_threshold', 60)
        self.sma_period = get_strategy_param('momentum_breakout', 'sma_period', 20)
        self.volume_multiple = get_strategy_param('momentum_breakout', 'volume_multiple', 1.5)
        self.atr_period = get_strategy_param('momentum_breakout', 'atr_period', 14)
        self.trailing_stop_atr_multiplier = get_strategy_param('momentum_breakout', 'trailing_stop_atr_multiplier', 2.0)
        self.hard_stop_pct = get_strategy_param('momentum_breakout', 'hard_stop_pct', -0.03)

    def generate_signals(self, symbols: list[str], market_data: Dict[str, Any]) -> list[Signal]:
        signals = []
        for symbol in symbols:
            data = market_data.get(symbol)
            if not data:
                continue

            rsi = data.get('rsi', 0)
            price = data.get('price', 0)
            sma_20 = data.get('sma_20', float('inf'))
            volume = data.get('volume', 0)
            avg_volume_20 = data.get('avg_volume_20', 1)
            atr = data.get('atr_14', 0)
            
            # Simple previous price tracking check in reality, simplified here
            prev_price = data.get('prev_price', price)

            # Price crossing above SMA and conditions met
            if rsi > self.rsi_threshold and price > sma_20 and prev_price <= sma_20 and volume > (self.volume_multiple * avg_volume_20):
                confidence = min(1.0, (rsi / 100.0) * (volume / avg_volume_20) * 0.5)
                stop_loss = max(price - (atr * self.trailing_stop_atr_multiplier), price * (1 + self.hard_stop_pct))
                take_profit = price + (price - stop_loss) * 2.0  # 2:1 R/R

                signals.append(Signal(
                    symbol=symbol,
                    direction="LONG",
                    strategy_name="momentum_breakout",
                    confidence=confidence,
                    entry_price=price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    order_type="MARKET",
                    asset_type="EQUITY"
                ))
        return signals

    def should_exit(self, position: Any, market_data: Dict[str, Any]) -> Optional[ExitSignal]:
        data = market_data.get(position.symbol)
        if not data:
            return None
        
        current_price = data.get('price', 0)
        
        if current_price <= position.stop_loss:
            return ExitSignal(
                symbol=position.symbol,
                reason="Hard Stop Hit",
                urgency="IMMEDIATE"
            )
        elif hasattr(position, 'trailing_stop') and position.trailing_stop and current_price <= position.trailing_stop:
            return ExitSignal(
                symbol=position.symbol,
                reason="Trailing Stop Hit",
                urgency="IMMEDIATE"
            )
            
        return None
