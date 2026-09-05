"""
Portfolio State Tracker
"""
from dataclasses import dataclass
from typing import Dict, Optional, Any

@dataclass
class Position:
    """Represents an open trading position."""
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    stop_loss: float  # Absolute price stop
    stop_loss_pct: float  # Percentage stop (e.g., -0.05)
    trailing_stop: float  # Legacy alias
    trailing_stop_price: float  # Current trailing stop price
    trailing_stop_atr_multiple: float  # ATR multiplier for trailing stop
    highest_price_since_entry: float  # Tracks high watermark for trailing stop
    strategy_name: str
    asset_type: str  # "EQUITY" or "OPTION"
    entry_time: Optional[Any] = None  # datetime or unix timestamp
    unrealized_pnl: float = 0.0
    take_profit_price: Optional[float] = None
    option_details: Optional[Any] = None
    option_expiry: Optional[Any] = None  # datetime for theta decay checks


class PortfolioState:
    """Tracks the current state of the portfolio."""
    def __init__(self, initial_cash: float = 100000.0) -> None:
        self.positions: Dict[str, Position] = {}
        self.cash = initial_cash
        self.total_equity = initial_cash
        self.daily_pnl = 0.0
        self.daily_pnl_pct = 0.0
        self.options_allocation_pct = 0.0
        self.start_of_day_equity = initial_cash

    def add_position(self, position: Optional['Position'] = None, **kwargs) -> None:
        """
        Adds a position to the portfolio.
        Accepts either a Position object or keyword arguments.
        """
        if position is None:
            from datetime import datetime
            pos = Position(
                symbol=kwargs["symbol"],
                quantity=kwargs["quantity"],
                entry_price=kwargs["entry_price"],
                current_price=kwargs["entry_price"],
                stop_loss=kwargs["entry_price"] * (1 + kwargs.get("stop_loss_pct", -0.05)),
                stop_loss_pct=kwargs.get("stop_loss_pct", -0.05),
                trailing_stop=0.0,
                trailing_stop_price=kwargs.get("trailing_stop_price", 0.0),
                trailing_stop_atr_multiple=kwargs.get("trailing_stop_atr_multiple", 2.0),
                highest_price_since_entry=kwargs["entry_price"],
                strategy_name=kwargs.get("strategy_name", "unknown"),
                asset_type=kwargs.get("asset_type", "EQUITY"),
                entry_time=datetime.now(),
                take_profit_price=kwargs.get("take_profit_price"),
                option_details=kwargs.get("option_details"),
                option_expiry=kwargs.get("option_expiry"),
            )
            position = pos

        self.positions[position.symbol] = position
        cost = position.quantity * position.entry_price
        if position.asset_type == "OPTION":
            cost *= 100  # Standard option multiplier
        self.cash -= cost
        self.update_equity()

    def remove_position(self, symbol: str) -> None:
        """Removes a position from the portfolio and updates cash."""
        if symbol in self.positions:
            position = self.positions[symbol]
            value = position.quantity * position.current_price
            if position.asset_type == "OPTION":
                value *= 100
            self.cash += value
            del self.positions[symbol]
            self.update_equity()

    def update_prices(self, market_data: Dict[str, Any]) -> None:
        """Updates current prices for all open positions."""
        for symbol, position in self.positions.items():
            if symbol in market_data:
                data = market_data[symbol]
                if position.asset_type == 'EQUITY':
                    current_price = data.get('price', position.current_price)
                else:
                    current_price = data.get('options_data', {}).get(
                        position.option_details.strike if position.option_details else '', {}
                    ).get('price', position.current_price)
                
                position.current_price = current_price
                
                # Update trailing stop if necessary
                if hasattr(position, 'trailing_stop_distance'):
                    # Basic trailing stop logic
                    pass

                multiplier = 100 if position.asset_type == 'OPTION' else 1
                position.unrealized_pnl = (position.current_price - position.entry_price) * position.quantity * multiplier
                
        self.update_equity()

    def update_equity(self) -> None:
        """Recalculates total equity, daily P&L, and options allocation."""
        options_value = 0.0
        equity_value = 0.0
        
        for pos in self.positions.values():
            val = pos.quantity * pos.current_price
            if pos.asset_type == "OPTION":
                val *= 100
                options_value += val
            else:
                equity_value += val
                
        self.total_equity = self.cash + options_value + equity_value
        self.options_allocation_pct = options_value / self.total_equity if self.total_equity > 0 else 0.0
        self.daily_pnl = self.total_equity - self.start_of_day_equity
        self.daily_pnl_pct = self.daily_pnl / self.start_of_day_equity if self.start_of_day_equity > 0 else 0.0

    def get_portfolio_heat(self) -> float:
        """Calculates total portfolio risk (heat)."""
        total_risk = 0.0
        for pos in self.positions.values():
            multiplier = 100 if pos.asset_type == 'OPTION' else 1
            risk_per_share = pos.entry_price - pos.stop_loss
            if risk_per_share > 0:
                total_risk += risk_per_share * pos.quantity * multiplier
        
        return total_risk / self.total_equity if self.total_equity > 0 else 0.0

    def get_options_allocation(self) -> float:
        """Returns current options allocation percentage."""
        return self.options_allocation_pct
