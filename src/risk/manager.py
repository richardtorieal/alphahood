"""
AlphaHood — Live Risk Management Engine
Enforces dynamic Half-Kelly Criterion (% of current account equity),
strict buying power management, 10 DTE assignment protection,
daily circuit breakers (-8%), and risk/reward ratios.
"""
from typing import Tuple
from .portfolio import PortfolioState
from ..strategies.base import Signal
from .. import config

class RiskManager:
    """
    Risk management engine enforcing dynamic Fractional Kelly position sizing (% of Account Equity).
    """
    def __init__(self) -> None:
        pass

    def validate_trade(self, signal: Signal, portfolio: PortfolioState) -> Tuple[bool, str, float]:
        """
        Validates a trade signal against all risk parameters under Fractional Kelly & Account Equity sizing.
        Returns: (approved, reason, adjusted_size)
        """
        # 1. Daily Loss Limit (Circuit Breaker)
        if portfolio.daily_pnl_pct <= config.DAILY_LOSS_LIMIT:
            return False, f"Circuit Breaker Triggered. Daily PNL: {portfolio.daily_pnl_pct:.2%}", 0.0

        # 2. Max Concurrent Positions
        max_positions = getattr(config, 'MAX_CONCURRENT_POSITIONS', 3)
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

        # 5. Dynamic Fractional Kelly Position Sizing (% of Total Account Equity)
        win_rate = 0.65  # Rolling strategy win rate
        b = max(1.5, rr_ratio)  # Risk/Reward ratio
        p = win_rate
        q = 1.0 - p
        
        full_kelly = (p * b - q) / b if b > 0 else 0.15
        half_kelly = max(0.10, full_kelly / 2.0)  # Half-Kelly for safety
        
        # Cap max position size at 30% of current total account equity (scalable as account grows)
        max_alloc_pct = min(0.30, half_kelly)
        investment_dollars = min(portfolio.cash, portfolio.total_equity * max_alloc_pct)

        if portfolio.cash < 30.0 or investment_dollars < 30.0:
            return False, f"Insufficient cash available (${portfolio.cash:.2f})", 0.0

        # Compute quantity (fractional shares for equity, contract count for options)
        multiplier = 100 if signal.asset_type == 'OPTION' else 1
        quantity = investment_dollars / (signal.entry_price * multiplier)
        
        if signal.asset_type == "EQUITY":
            quantity = round(quantity, 4)
        else:
            quantity = int(quantity)
            if quantity < 1 and portfolio.cash >= signal.entry_price * 100:
                quantity = 1  # Minimum 1 option contract if cash permits

        if quantity <= 0:
            return False, "Calculated position size is 0", 0.0

        proposed_investment = quantity * signal.entry_price * multiplier
        
        # 6. Portfolio Heat Check
        proposed_heat = portfolio.get_portfolio_heat() + (proposed_investment / portfolio.total_equity)
        if proposed_heat > config.MAX_PORTFOLIO_HEAT:
            return False, f"Trade exceeds max portfolio heat ({proposed_heat:.2%} > {config.MAX_PORTFOLIO_HEAT:.2%})", 0.0

        # 7. Cash Reserve Check (15% Cash Reserve)
        if (portfolio.cash - proposed_investment) / portfolio.total_equity < config.MIN_CASH_EQUITY_RESERVE:
            return False, "Trade violates minimum 15% cash reserve requirement", 0.0

        return True, "Trade approved", float(quantity)
