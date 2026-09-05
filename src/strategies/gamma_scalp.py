"""
Gamma Scalp Strategy
"""
from typing import Optional, Dict, Any
from .base import BaseStrategy, Signal, ExitSignal, OptionDetails
from ..config import get_strategy_param

class GammaScalpStrategy(BaseStrategy):
    """
    Gamma Scalp Strategy:
    - Finds high-gamma, near-money options with 5-15 DTE
    - Entry when IV rank < 30 and directional bias confirmed by momentum
    - Exit: +50% profit target, -30% stop loss, or 3 DTE remaining
    - Selects optimal strike using delta targeting (0.3-0.5 delta)
    - Filters for liquid options (min open interest)
    """
    def __init__(self) -> None:
        self.min_dte = get_strategy_param('gamma_scalp', 'min_dte', 5)
        self.max_dte = get_strategy_param('gamma_scalp', 'max_dte', 15)
        self.max_iv_rank = get_strategy_param('gamma_scalp', 'max_iv_rank', 30)
        self.profit_target_pct = get_strategy_param('gamma_scalp', 'profit_target_pct', 0.50)
        self.stop_loss_pct = get_strategy_param('gamma_scalp', 'stop_loss_pct', -0.30)
        self.exit_dte = get_strategy_param('gamma_scalp', 'exit_dte', 3)
        self.min_delta = get_strategy_param('gamma_scalp', 'min_delta', 0.3)
        self.max_delta = get_strategy_param('gamma_scalp', 'max_delta', 0.5)
        self.min_open_interest = get_strategy_param('gamma_scalp', 'min_open_interest', 500)

    def generate_signals(self, symbols: list[str], market_data: Dict[str, Any]) -> list[Signal]:
        signals = []
        for symbol in symbols:
            data = market_data.get(symbol)
            if not data:
                continue

            iv_rank = data.get('iv_rank', 100)
            momentum_bias = data.get('momentum_bias', 0) # e.g. 1 for LONG, -1 for SHORT
            options_chain = data.get('options_chain', [])
            
            if iv_rank < self.max_iv_rank and momentum_bias != 0:
                # Find optimal option
                optimal_option = None
                for opt in options_chain:
                    dte = opt.get('dte', 0)
                    delta = abs(opt.get('delta', 0))
                    oi = opt.get('open_interest', 0)
                    
                    if self.min_dte <= dte <= self.max_dte and \
                       self.min_delta <= delta <= self.max_delta and \
                       oi >= self.min_open_interest:
                        # Check direction match
                        if (momentum_bias > 0 and opt.get('type') == 'CALL') or \
                           (momentum_bias < 0 and opt.get('type') == 'PUT'):
                            optimal_option = opt
                            break
                            
                if optimal_option:
                    opt_price = optimal_option.get('price', 0)
                    signals.append(Signal(
                        symbol=symbol,
                        direction="LONG", # Buying the option
                        strategy_name="gamma_scalp",
                        confidence=0.8,
                        entry_price=opt_price,
                        stop_loss=opt_price * (1 + self.stop_loss_pct),
                        take_profit=opt_price * (1 + self.profit_target_pct),
                        order_type="MARKET",
                        asset_type="OPTION",
                        option_details=OptionDetails(
                            contract_type=optimal_option.get('type', 'CALL'),
                            strike=optimal_option.get('strike', 0),
                            expiration=optimal_option.get('expiration', ''),
                            greeks={
                                'delta': optimal_option.get('delta', 0),
                                'gamma': optimal_option.get('gamma', 0),
                                'theta': optimal_option.get('theta', 0),
                                'vega': optimal_option.get('vega', 0)
                            }
                        )
                    ))
        return signals

    def should_exit(self, position: Any, market_data: Dict[str, Any]) -> Optional[ExitSignal]:
        if position.asset_type != 'OPTION' or not position.option_details:
            return None
            
        data = market_data.get(position.symbol, {})
        opt_data = data.get('options_data', {}).get(position.option_details.strike, {})
        
        current_price = opt_data.get('price', position.current_price)
        dte = opt_data.get('dte', 99)
        
        if current_price <= position.stop_loss:
            return ExitSignal(symbol=position.symbol, reason="Stop Loss Hit", urgency="IMMEDIATE")
        elif current_price >= position.take_profit:
            return ExitSignal(symbol=position.symbol, reason="Profit Target Hit", urgency="NORMAL")
        elif dte <= self.exit_dte:
            return ExitSignal(symbol=position.symbol, reason="DTE Exit Trigger", urgency="NORMAL")
            
        return None
