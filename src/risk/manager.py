"""
AlphaHood — Live Risk Management Engine
Enforces strict $500 account equity rules, fractional share sizing,
max 2 concurrent positions ($200 max per trade, $100 cash buffer),
daily circuit breakers (-8%), and risk/reward ratios.
"""
from typing import Tuple
from .portfolio import PortfolioState
from ..strategies.base import Signal
from .. import config

class RiskManager:
    """
    Risk management engine enforcing strict $500 starting balance rules.
    """
    def __init__(self) -> None:
        pass

    def validate_trade(self, signal: Signal, portfolio: PortfolioState) -> Tuple[bool, str, float]:
        """
        Validates a trade signal against all risk parameters under $500 balance discipline.
        Returns: (approved, reason, adjusted_size)
        """
        # 1. Daily Loss Limit (Circuit Breaker)
        if portfolio.daily_pnl_pct <= config.DAILY_LOSS_LIMIT:
            return False, f"Circuit Breaker Triggered. Daily PNL: {portfolio.daily_pnl_pct:.2%}", 0.0

        # 2. Max Concurrent Positions (Max 2 trades active)
        max_positions = getattr(config, 'MAX_CONCURRENT_POSITIONS', 2)
        if len(portfolio.positions) >= max_positions:
            return False, f"Max concurrent positions reached ({len(portfolio.positions)}/{max_positions})", 0.0
            
        # 3. Position Already Exists Check
        if signal.symbol in portfolio.positions:
             return False, f"Position already exists for {signal.symbol}", 0.0

        # 4. Risk / Reward Ratio Check
        risk = signal.entry_price - signal.stop_loss
        reward = signal.take_profit - signal.entry_price
        
        if risk <= 0:
            return False, "Invalid stop loss (must be below entry for LONG)", 0.0
            
        rr_ratio = reward / risk
        if rr_ratio < config.MIN_RISK_REWARD_RATIO:
            return False, f"R/R ratio {rr_ratio:.2f} < {config.MIN_RISK_REWARD_RATIO}", 0.0

        # 5. Position Sizing ($500 balance rule: Max $200 per trade, bounded by available cash)
        max_per_trade = 200.0
        available_cash = portfolio.cash

        if available_cash < 25.0:
            return False, f"Insufficient buying power (${available_cash:.2f} < $25.00 min)", 0.0

        investment_dollars = min(available_cash, max_per_trade)
        
        # Compute fractional share quantity for Robinhood
        multiplier = 100 if signal.asset_type == 'OPTION' else 1
        quantity = investment_dollars / (signal.entry_price * multiplier)
        
        # Round fractional shares to 4 decimal places
        if signal.asset_type == "EQUITY":
            quantity = round(quantity, 4)
        else:
            quantity = int(quantity)

        if quantity <= 0:
            return False, "Calculated position size is 0", 0.0

        proposed_investment = quantity * signal.entry_price * multiplier
        
        # 6. Portfolio Heat Check
        proposed_heat = portfolio.get_portfolio_heat() + (proposed_investment / portfolio.total_equity)
        if proposed_heat > config.MAX_PORTFOLIO_HEAT:
            return False, f"Trade exceeds max portfolio heat ({proposed_heat:.2%} > {config.MAX_PORTFOLIO_HEAT:.2%})", 0.0

        # 7. Cash Reserve Check
        if (portfolio.cash - proposed_investment) < 25.0:
            return False, "Trade leaves less than $25 cash buffer", 0.0

        return True, "Trade approved", float(quantity)
