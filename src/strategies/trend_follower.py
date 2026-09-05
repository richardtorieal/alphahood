"""
Trend Follower Strategy
"""
from typing import Optional, Dict, Any
from .base import BaseStrategy, Signal, ExitSignal
from ..config import get_strategy_param

class TrendFollowerStrategy(BaseStrategy):
    """
    Trend Follower Strategy:
    - 10/50 EMA golden cross + ADX(14) > 25
    - Entry: Market order on cross confirmation
    - Exit: Death cross (10 EMA < 50 EMA), trailing stop at 3x ATR(14)
    - Trend strength scoring using ADX value
    - Longer hold period (swing trader, days to weeks)
    """
    def __init__(self) -> None:
        self.fast_ema_period = get_strategy_param('trend_follower', 'fast_ema_period', 10)
        self.slow_ema_period = get_strategy_param('trend_follower', 'slow_ema_period', 50)
        self.adx_period = get_strategy_param('trend_follower', 'adx_period', 14)
        self.adx_threshold = get_strategy_param('trend_follower', 'adx_threshold', 25)
        self.atr_period = get_strategy_param('trend_follower', 'atr_period', 14)
        self.trailing_stop_atr_multiplier = get_strategy_param('trend_follower', 'trailing_stop_atr_multiplier', 3.0)

    def generate_signals(self, symbols: list[str], market_data: Dict[str, Any]) -> list[Signal]:
        signals = []
        for symbol in symbols:
            data = market_data.get(symbol)
            if not data:
                continue

            ema_10 = data.get('ema_10', 0)
            ema_50 = data.get('ema_50', 0)
            prev_ema_10 = data.get('prev_ema_10', ema_10)
            prev_ema_50 = data.get('prev_ema_50', ema_50)
            adx = data.get('adx', 0)
            price = data.get('price', 0)
            atr = data.get('atr_14', 0)

            # Golden cross detection
            golden_cross = (prev_ema_10 <= prev_ema_50) and (ema_10 > ema_50)

            if golden_cross and adx > self.adx_threshold:
                confidence = min(1.0, adx / 100.0 + 0.3)
                stop_loss = price - (atr * self.trailing_stop_atr_multiplier)
                
                signals.append(Signal(
                    symbol=symbol,
                    direction="LONG",
                    strategy_name="trend_follower",
                    confidence=confidence,
                    entry_price=price,
                    stop_loss=stop_loss,
                    take_profit=price * 2, # No fixed take profit, riding the trend, but giving a placeholder
                    order_type="MARKET",
                    asset_type="EQUITY"
                ))
        return signals

    def should_exit(self, position: Any, market_data: Dict[str, Any]) -> Optional[ExitSignal]:
        data = market_data.get(position.symbol)
        if not data:
            return None
            
        current_price = data.get('price', 0)
        ema_10 = data.get('ema_10', 0)
        ema_50 = data.get('ema_50', 0)
        prev_ema_10 = data.get('prev_ema_10', ema_10)
        prev_ema_50 = data.get('prev_ema_50', ema_50)
        
        # Death cross detection
        death_cross = (prev_ema_10 >= prev_ema_50) and (ema_10 < ema_50)
        
        if death_cross:
            return ExitSignal(symbol=position.symbol, reason="Death Cross (Trend Reversal)", urgency="NORMAL")
        elif hasattr(position, 'trailing_stop') and position.trailing_stop and current_price <= position.trailing_stop:
            return ExitSignal(symbol=position.symbol, reason="Trailing Stop Hit", urgency="IMMEDIATE")
        elif current_price <= position.stop_loss:
            return ExitSignal(symbol=position.symbol, reason="Stop Loss Hit", urgency="IMMEDIATE")
            
        return None
