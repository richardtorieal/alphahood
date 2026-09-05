"""
Risk Management Engine
"""
from typing import Tuple
from .portfolio import PortfolioState
from ..strategies.base import Signal
from .. import config

class RiskManager:
    """
    Complete risk management engine.
    """
    def __init__(self) -> None:
        pass

    def validate_trade(self, signal: Signal, portfolio: PortfolioState) -> Tuple[bool, str, float]:
        """
        Validates a trade signal against all risk parameters.
        Returns: (approved, reason, adjusted_size)
        """
        # 1. Daily Loss Limit (Circuit Breaker)
        if portfolio.daily_pnl_pct <= config.DAILY_LOSS_LIMIT:
            return False, f"Circuit Breaker Triggered. Daily PNL: {portfolio.daily_pnl_pct:.2%}", 0.0

        # 2. Max Concurrent Positions
        if len(portfolio.positions) >= config.MAX_CONCURRENT_POSITIONS:
            return False, f"Max concurrent positions reached ({config.MAX_CONCURRENT_POSITIONS})", 0.0
            
        # 3. Position Already Exists (Simplified: skip adding to existing)
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

        # 5. Position Sizing (Fractional Kelly / Risk-based)
        # Using a simpler risk-based approach bound by MAX_POSITION_SIZE_PCT
        # E.g., risk 1% of portfolio per trade
        max_portfolio_risk_per_trade = 0.01 
        allowed_risk_amount = portfolio.total_equity * max_portfolio_risk_per_trade
        
        multiplier = 100 if signal.asset_type == 'OPTION' else 1
        
        # Quantity based on risk
        raw_quantity = allowed_risk_amount / (risk * multiplier)
        
        # Max position size constraint
        max_investment = portfolio.total_equity * config.MAX_POSITION_SIZE_PCT
        max_quantity_by_size = max_investment / (signal.entry_price * multiplier)
        
        adjusted_quantity = min(raw_quantity, max_quantity_by_size)
        
        # Floor to integer for equity/options
        adjusted_quantity = int(adjusted_quantity)
        
        if adjusted_quantity <= 0:
            return False, "Calculated position size is 0", 0.0

        proposed_investment = adjusted_quantity * signal.entry_price * multiplier
        
        # 6. Portfolio Heat Check
        proposed_heat = portfolio.get_portfolio_heat() + (allowed_risk_amount / portfolio.total_equity)
        if proposed_heat > config.MAX_PORTFOLIO_HEAT:
            return False, f"Trade exceeds max portfolio heat ({proposed_heat:.2%} > {config.MAX_PORTFOLIO_HEAT:.2%})", 0.0

        # 7. Asset Allocation Constraints
        if signal.asset_type == "OPTION":
            proposed_opt_alloc = (portfolio.total_equity * portfolio.options_allocation_pct + proposed_investment) / portfolio.total_equity
            if proposed_opt_alloc > config.MAX_OPTIONS_ALLOCATION:
                return False, f"Exceeds max options allocation ({proposed_opt_alloc:.2%} > {config.MAX_OPTIONS_ALLOCATION:.2%})", 0.0
        
        # 8. Cash/Equity Reserve
        proposed_cash = portfolio.cash - proposed_investment
        if proposed_cash / portfolio.total_equity < config.MIN_CASH_EQUITY_RESERVE:
             return False, f"Fails minimum cash reserve requirement", 0.0

        return True, "Trade approved", float(adjusted_quantity)
