"""
AlphaHood — High-Frequency Position Monitor
Checks stops, trailing stops, theta decay, and live P&L every 5 minutes.
Auto-executes exits when stops are triggered.
"""
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from .risk.portfolio import PortfolioState, Position
from .data.market_data import MarketDataProvider
from .data.options_data import OptionsDataProvider
from .utils.discord_notify import send_trade_alert, send_exit_alert
from .config import (
    STOP_LOSS_HARD_PCT,
    DAILY_LOSS_LIMIT_PCT,
)

log = logging.getLogger("alphahood.monitor")

# ── Constants ──────────────────────────────────────────────────────────────────
THETA_DECAY_WARNING_DTE = 1  # Alert when option has <= 1 DTE
THETA_DECAY_AUTO_CLOSE_DTE = 0  # Auto-close at 0 DTE
TRAILING_STOP_UPDATE_THRESHOLD = 0.001  # Min price move to update trailing stop


@dataclass
class ExitOrder:
    """An exit order to be executed by the agent."""
    symbol: str
    quantity: float
    side: str  # "sell"
    reason: str
    urgency: str  # "IMMEDIATE" or "NORMAL"
    asset_type: str  # "EQUITY" or "OPTION"
    strategy_name: str


@dataclass
class ThetaWarning:
    """Warning for options approaching expiration."""
    symbol: str
    dte: int
    current_value: float
    recommendation: str  # "CLOSE" or "MONITOR"


@dataclass
class PnLSummary:
    """Portfolio-level P&L summary."""
    total_unrealized_pnl: float = 0.0
    total_unrealized_pnl_pct: float = 0.0
    daily_realized_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    best_performer: Optional[str] = None
    best_performer_pnl_pct: float = 0.0
    worst_performer: Optional[str] = None
    worst_performer_pnl_pct: float = 0.0
    positions_in_profit: int = 0
    positions_in_loss: int = 0
    circuit_breaker_triggered: bool = False


class PositionMonitor:
    """
    High-frequency monitor that runs every 5 minutes during market hours.
    Checks all open positions against stop-loss / trailing-stop levels,
    monitors theta decay, and calculates live P&L.
    """

    def __init__(
        self,
        market_data: MarketDataProvider,
        options_data: Optional[OptionsDataProvider] = None,
    ):
        self.market_data = market_data
        self.options_data = options_data

    def check_stops(self, portfolio: PortfolioState) -> list[ExitOrder]:
        """
        Check all open positions against their stop-loss and trailing-stop levels.
        Returns a list of ExitOrders for positions that need to be closed.
        """
        exit_orders: list[ExitOrder] = []

        for symbol, position in portfolio.positions.items():
            current_price = self.market_data.get_current_price(symbol)
            if current_price <= 0:
                log.warning(f"Could not get price for {symbol}, skipping stop check")
                continue

            # Update current price in portfolio
            position.current_price = current_price
            pnl_pct = (current_price - position.entry_price) / position.entry_price

            # 1. Hard stop-loss check
            if pnl_pct <= position.stop_loss_pct:
                exit_orders.append(ExitOrder(
                    symbol=symbol,
                    quantity=position.quantity,
                    side="sell",
                    reason=f"HARD STOP triggered at {pnl_pct:.1%} (limit: {position.stop_loss_pct:.1%})",
                    urgency="IMMEDIATE",
                    asset_type=position.asset_type,
                    strategy_name=position.strategy_name,
                ))
                log.warning(f"🛑 HARD STOP: {symbol} at {pnl_pct:.1%}")
                continue

            # 2. Trailing stop check
            if position.trailing_stop_price and position.trailing_stop_price > 0:
                if current_price <= position.trailing_stop_price:
                    exit_orders.append(ExitOrder(
                        symbol=symbol,
                        quantity=position.quantity,
                        side="sell",
                        reason=f"TRAILING STOP hit at ${current_price:.2f} (stop: ${position.trailing_stop_price:.2f})",
                        urgency="IMMEDIATE",
                        asset_type=position.asset_type,
                        strategy_name=position.strategy_name,
                    ))
                    log.warning(f"📉 TRAILING STOP: {symbol} at ${current_price:.2f}")
                    continue

            # 3. Take-profit check (if set)
            if position.take_profit_price and current_price >= position.take_profit_price:
                exit_orders.append(ExitOrder(
                    symbol=symbol,
                    quantity=position.quantity,
                    side="sell",
                    reason=f"TAKE PROFIT target reached at ${current_price:.2f} (target: ${position.take_profit_price:.2f})",
                    urgency="NORMAL",
                    asset_type=position.asset_type,
                    strategy_name=position.strategy_name,
                ))
                log.info(f"🎯 TAKE PROFIT: {symbol} at ${current_price:.2f}")

        return exit_orders

    def update_trailing_stops(self, portfolio: PortfolioState) -> dict[str, float]:
        """
        Update trailing stops for positions that have moved favorably.
        Returns dict of symbol -> new trailing stop price.
        """
        updated_stops: dict[str, float] = {}

        for symbol, position in portfolio.positions.items():
            if not position.trailing_stop_price or position.trailing_stop_atr_multiple <= 0:
                continue

            current_price = position.current_price
            if current_price <= 0:
                continue

            # Only update if price has moved up (new high)
            if current_price > position.highest_price_since_entry:
                position.highest_price_since_entry = current_price

                # Recalculate trailing stop based on ATR
                atr = self.market_data.get_atr(symbol)
                if atr and atr > 0:
                    new_stop = current_price - (atr * position.trailing_stop_atr_multiple)
                    # Only ratchet up, never down
                    if new_stop > position.trailing_stop_price:
                        old_stop = position.trailing_stop_price
                        position.trailing_stop_price = new_stop
                        updated_stops[symbol] = new_stop
                        log.info(
                            f"📈 Trailing stop updated: {symbol} "
                            f"${old_stop:.2f} → ${new_stop:.2f} "
                            f"(price: ${current_price:.2f})"
                        )

        return updated_stops

    def check_theta_decay(self, portfolio: PortfolioState) -> list[ThetaWarning]:
        """
        Monitor options positions for theta decay risk.
        Alert when DTE <= 1, auto-close recommendation at 0 DTE.
        """
        warnings: list[ThetaWarning] = []

        for symbol, position in portfolio.positions.items():
            if position.asset_type != "OPTION" or not position.option_expiry:
                continue

            now = datetime.now(timezone.utc)
            dte = (position.option_expiry - now).days

            if dte <= THETA_DECAY_AUTO_CLOSE_DTE:
                warnings.append(ThetaWarning(
                    symbol=symbol,
                    dte=dte,
                    current_value=position.current_price * position.quantity,
                    recommendation="CLOSE",
                ))
                log.warning(f"⏰ THETA DECAY CRITICAL: {symbol} expires TODAY (0 DTE)")
            elif dte <= THETA_DECAY_WARNING_DTE:
                warnings.append(ThetaWarning(
                    symbol=symbol,
                    dte=dte,
                    current_value=position.current_price * position.quantity,
                    recommendation="MONITOR",
                ))
                log.info(f"⚠️ Theta warning: {symbol} has {dte} DTE remaining")

        return warnings

    def calculate_live_pnl(self, portfolio: PortfolioState) -> PnLSummary:
        """
        Calculate real-time P&L across all positions and check circuit breaker.
        """
        summary = PnLSummary()
        best_pnl = float("-inf")
        worst_pnl = float("inf")

        for symbol, position in portfolio.positions.items():
            pnl = (position.current_price - position.entry_price) * position.quantity
            pnl_pct = (position.current_price - position.entry_price) / position.entry_price if position.entry_price > 0 else 0.0

            summary.total_unrealized_pnl += pnl

            if pnl >= 0:
                summary.positions_in_profit += 1
            else:
                summary.positions_in_loss += 1

            if pnl_pct > best_pnl:
                best_pnl = pnl_pct
                summary.best_performer = symbol
                summary.best_performer_pnl_pct = pnl_pct

            if pnl_pct < worst_pnl:
                worst_pnl = pnl_pct
                summary.worst_performer = symbol
                summary.worst_performer_pnl_pct = pnl_pct

        # Calculate portfolio-level P&L percentage
        if portfolio.total_equity > 0:
            summary.total_unrealized_pnl_pct = summary.total_unrealized_pnl / portfolio.total_equity
            summary.daily_pnl_pct = portfolio.daily_pnl / portfolio.total_equity

        # Circuit breaker check
        if summary.daily_pnl_pct <= DAILY_LOSS_LIMIT_PCT:
            summary.circuit_breaker_triggered = True
            log.critical(
                f"🚨 CIRCUIT BREAKER: Daily loss {summary.daily_pnl_pct:.1%} "
                f"exceeds limit {DAILY_LOSS_LIMIT_PCT:.1%}. HALTING ALL TRADING."
            )

        return summary
