"""
AlphaHood — Agent Orchestrator
Main entry point that ties together strategies, risk management,
MCP execution, position monitoring, and LLM-assisted reviews.
Implements the dual-frequency swing trader monitoring framework.
"""
import argparse
import logging
import signal
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import (
    MONITOR_INTERVAL_SECONDS,
    THETA_CHECK_INTERVAL_SECONDS,
    LLM_REVIEW_TIMES,
    STRATEGY_SCAN_TIME,
    MAX_OPTIONS_ALLOCATION_PCT,
)
from .mcp_client import RobinhoodMCP
from .data.market_data import MarketDataProvider
from .data.options_data import OptionsDataProvider
from .strategies.momentum_breakout import MomentumBreakoutStrategy
from .strategies.gamma_scalp import GammaScalpStrategy
from .strategies.mean_reversion import MeanReversionStrategy
from .strategies.trend_follower import TrendFollowerStrategy
from .risk.manager import RiskManager
from .risk.portfolio import PortfolioState
from .monitor import PositionMonitor
from .trade_reviewer import TradeReviewer
from .utils.logger import get_logger
from .utils.discord_notify import send_trade_alert, send_exit_alert, send_daily_summary

log = get_logger("alphahood.agent")

# ── Default watchlist for scanning ─────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD",
    "CRM", "NFLX", "AVGO", "ORCL", "ADBE", "SHOP", "SQ", "COIN",
    "MARA", "RIOT", "PLTR", "SOFI", "UBER", "ABNB", "SNOW", "NET",
    "CRWD", "DDOG", "MDB", "ZS", "PANW", "ANET",
]


class AlphaHoodAgent:
    """
    Main orchestrator for the AlphaHood agentic trading system.
    Manages strategy lifecycle, risk validation, order execution,
    high-frequency monitoring, and LLM-assisted reviews.
    """

    def __init__(self, paper_mode: bool = True):
        log.info("=" * 60)
        log.info("AlphaHood Agent Initializing")
        log.info(f"Mode: {'PAPER' if paper_mode else '🔴 LIVE'}")
        log.info("=" * 60)

        # Core components
        self.mcp = RobinhoodMCP()
        self.market_data = MarketDataProvider()
        self.options_data = OptionsDataProvider()
        self.risk_manager = RiskManager()
        self.portfolio = PortfolioState()
        self.monitor = PositionMonitor(self.market_data, self.options_data)
        self.reviewer = TradeReviewer()

        # Strategies
        self.strategies = [
            MomentumBreakoutStrategy(),
            GammaScalpStrategy(),
            MeanReversionStrategy(),
            TrendFollowerStrategy(),
        ]
        log.info(f"Loaded {len(self.strategies)} strategies: "
                 f"{', '.join(s.name for s in self.strategies)}")

        # Scheduler
        self.scheduler = BlockingScheduler()
        self._running = True

    # ── Strategy Scan (Pre-Market) ─────────────────────────────────────────────

    def run_scan(self, symbols: list[str] | None = None):
        """
        Run all strategies against the watchlist, validate signals through
        risk manager, and execute approved trades via MCP.
        """
        symbols = symbols or DEFAULT_WATCHLIST
        log.info(f"📡 Running strategy scan across {len(symbols)} symbols...")

        all_signals = []
        for strategy in self.strategies:
            try:
                signals = strategy.generate_signals(symbols, self.market_data)
                if signals:
                    log.info(f"  [{strategy.name}] generated {len(signals)} signal(s)")
                    all_signals.extend(signals)
            except Exception as e:
                log.error(f"  [{strategy.name}] scan error: {e}")

        if not all_signals:
            log.info("No signals generated across all strategies.")
            return

        # Sort by confidence descending
        all_signals.sort(key=lambda s: s.confidence, reverse=True)

        # Validate through risk manager and execute
        executed = 0
        for sig in all_signals:
            approved, reason, adjusted_size = self.risk_manager.validate_trade(
                sig, self.portfolio
            )
            if approved:
                log.info(f"✅ APPROVED: {sig.symbol} ({sig.strategy_name}) — size: {adjusted_size:.0f}")
                self._execute_trade(sig, adjusted_size)
                executed += 1
            else:
                log.info(f"❌ REJECTED: {sig.symbol} — {reason}")

        log.info(f"Scan complete: {executed}/{len(all_signals)} signals executed.")

    def _execute_trade(self, signal, quantity: float):
        """Execute a trade through the Robinhood MCP client."""
        try:
            if signal.asset_type == "OPTION" and signal.option_details:
                order = self.mcp.place_option_order(
                    symbol=signal.symbol,
                    contract_type=signal.option_details.contract_type,
                    strike=signal.option_details.strike,
                    expiry=signal.option_details.expiration,
                    side="buy",
                    qty=int(quantity),
                )
            else:
                order = self.mcp.place_equity_order(
                    symbol=signal.symbol,
                    side="buy",
                    qty=int(quantity),
                    order_type=signal.order_type,
                    limit_price=signal.entry_price if signal.order_type == "LIMIT" else None,
                )

            # Track in portfolio
            self.portfolio.add_position(
                symbol=signal.symbol,
                quantity=quantity,
                entry_price=signal.entry_price,
                stop_loss_pct=signal.stop_loss if signal.stop_loss else -0.05,
                strategy_name=signal.strategy_name,
                asset_type=signal.asset_type,
            )

            # Discord alert
            send_trade_alert({
                "symbol": signal.symbol,
                "strategy": signal.strategy_name,
                "direction": signal.direction,
                "quantity": quantity,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "asset_type": signal.asset_type,
                "confidence": signal.confidence,
            })

        except Exception as e:
            log.error(f"Trade execution failed for {signal.symbol}: {e}")

    # ── High-Frequency Monitor (Every 5 min) ───────────────────────────────────

    def run_monitor(self):
        """
        High-frequency position check: stops, trailing stops, P&L.
        Runs every 5 minutes during market hours.
        """
        if not self.portfolio.positions:
            return

        log.info(f"🔄 Monitor check — {len(self.portfolio.positions)} positions")

        # 1. Update trailing stops
        updated = self.monitor.update_trailing_stops(self.portfolio)
        if updated:
            log.info(f"  Updated {len(updated)} trailing stop(s)")

        # 2. Check stops
        exit_orders = self.monitor.check_stops(self.portfolio)
        for order in exit_orders:
            log.warning(f"  EXIT: {order.symbol} — {order.reason}")
            self._execute_exit(order)

        # 3. Live P&L
        pnl = self.monitor.calculate_live_pnl(self.portfolio)
        if pnl.circuit_breaker_triggered:
            log.critical("🚨 CIRCUIT BREAKER — halting all new entries")
            self.risk_manager.circuit_breaker_active = True

    def _execute_exit(self, exit_order):
        """Execute an exit order and update portfolio."""
        try:
            if exit_order.asset_type == "OPTION":
                self.mcp.place_option_order(
                    symbol=exit_order.symbol,
                    contract_type="",
                    strike=0,
                    expiry="",
                    side="sell",
                    qty=int(exit_order.quantity),
                )
            else:
                self.mcp.place_equity_order(
                    symbol=exit_order.symbol,
                    side="sell",
                    qty=int(exit_order.quantity),
                    order_type="MARKET",
                )

            self.portfolio.remove_position(exit_order.symbol)

            send_exit_alert({
                "symbol": exit_order.symbol,
                "reason": exit_order.reason,
                "strategy": exit_order.strategy_name,
                "urgency": exit_order.urgency,
            })

        except Exception as e:
            log.error(f"Exit execution failed for {exit_order.symbol}: {e}")

    # ── Theta Decay Monitor (Every 15 min) ─────────────────────────────────────

    def run_theta_check(self):
        """Check options positions for theta decay risk."""
        warnings = self.monitor.check_theta_decay(self.portfolio)
        for w in warnings:
            if w.recommendation == "CLOSE":
                log.warning(f"⏰ Auto-closing {w.symbol} (0 DTE)")
                # Create exit order for expired options
                if w.symbol in self.portfolio.positions:
                    pos = self.portfolio.positions[w.symbol]
                    from .monitor import ExitOrder
                    self._execute_exit(ExitOrder(
                        symbol=w.symbol,
                        quantity=pos.quantity,
                        side="sell",
                        reason=f"Theta decay: {w.dte} DTE",
                        urgency="IMMEDIATE",
                        asset_type="OPTION",
                        strategy_name=pos.strategy_name,
                    ))

    # ── LLM-Assisted Review (2x Daily) ─────────────────────────────────────────

    def run_review(self):
        """
        Run Gemini-powered trade review on all open positions.
        Posts structured analysis to Discord.
        """
        if not self.portfolio.positions:
            log.info("No positions to review.")
            return

        log.info(f"🧠 Running LLM trade review for {len(self.portfolio.positions)} positions...")
        review = self.reviewer.review_portfolio(self.portfolio, self.market_data)
        log.info(f"Review complete — Health: {review.overall_health}")

        # Apply EXIT recommendations automatically if high confidence
        for pr in review.position_reviews:
            if pr.recommendation == "EXIT" and pr.confidence >= 0.8:
                log.warning(f"LLM EXIT recommendation for {pr.symbol} (conf: {pr.confidence:.0%})")
                # Flag but don't auto-execute LLM exits — require human confirmation
                # unless circuit breaker is active

    # ── Daily Summary ──────────────────────────────────────────────────────────

    def run_daily_summary(self):
        """Post end-of-day portfolio summary to Discord."""
        pnl = self.monitor.calculate_live_pnl(self.portfolio)
        send_daily_summary({
            "total_positions": len(self.portfolio.positions),
            "unrealized_pnl": pnl.total_unrealized_pnl,
            "unrealized_pnl_pct": pnl.total_unrealized_pnl_pct,
            "daily_pnl_pct": pnl.daily_pnl_pct,
            "best": f"{pnl.best_performer} ({pnl.best_performer_pnl_pct:.1%})" if pnl.best_performer else "N/A",
            "worst": f"{pnl.worst_performer} ({pnl.worst_performer_pnl_pct:.1%})" if pnl.worst_performer else "N/A",
            "in_profit": pnl.positions_in_profit,
            "in_loss": pnl.positions_in_loss,
            "options_alloc": self.portfolio.get_options_allocation(),
        })

    # ── Scheduler Setup ────────────────────────────────────────────────────────

    def start_scheduler(self):
        """Configure and start all scheduled tasks."""
        # High-frequency: position monitor every 5 minutes
        self.scheduler.add_job(
            self.run_monitor,
            IntervalTrigger(seconds=MONITOR_INTERVAL_SECONDS),
            id="position_monitor",
            name="Position Monitor (5min)",
        )

        # Theta decay check every 15 minutes
        self.scheduler.add_job(
            self.run_theta_check,
            IntervalTrigger(seconds=THETA_CHECK_INTERVAL_SECONDS),
            id="theta_check",
            name="Theta Decay Monitor (15min)",
        )

        # LLM reviews at configured times (default: 10:30 AM, 3:30 PM CT)
        for review_time in LLM_REVIEW_TIMES:
            hour, minute = review_time.split(":")
            self.scheduler.add_job(
                self.run_review,
                CronTrigger(hour=int(hour), minute=int(minute)),
                id=f"llm_review_{review_time}",
                name=f"LLM Review ({review_time})",
            )

        # Pre-market strategy scan
        scan_hour, scan_minute = STRATEGY_SCAN_TIME.split(":")
        self.scheduler.add_job(
            self.run_scan,
            CronTrigger(hour=int(scan_hour), minute=int(scan_minute)),
            id="strategy_scan",
            name=f"Strategy Scan ({STRATEGY_SCAN_TIME})",
        )

        # Daily summary at market close (4:00 PM CT)
        self.scheduler.add_job(
            self.run_daily_summary,
            CronTrigger(hour=16, minute=5),
            id="daily_summary",
            name="Daily Summary (4:05 PM)",
        )

        log.info("📅 Scheduler configured:")
        for job in self.scheduler.get_jobs():
            log.info(f"  • {job.name}")

        # Graceful shutdown
        def _shutdown(signum, frame):
            log.info("Shutting down AlphaHood agent...")
            self.scheduler.shutdown(wait=False)
            sys.exit(0)

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        log.info("AlphaHood agent running. Press Ctrl+C to exit.")
        self.scheduler.start()


# ── CLI Entry Point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AlphaHood — Agentic Robinhood Trading System"
    )
    parser.add_argument("--scan", action="store_true", help="Run strategy scan immediately")
    parser.add_argument("--monitor", action="store_true", help="Start position monitoring loop")
    parser.add_argument("--review", action="store_true", help="Run LLM trade review immediately")
    parser.add_argument("--backtest", action="store_true", help="Run backtests on all strategies")
    parser.add_argument("--paper", action="store_true", default=True, help="Paper trading mode (default)")
    parser.add_argument("--live", action="store_true", help="Live trading mode (⚠️ real money)")
    parser.add_argument("--daemon", action="store_true", help="Start full daemon with all scheduled tasks")
    args = parser.parse_args()

    paper_mode = not args.live
    agent = AlphaHoodAgent(paper_mode=paper_mode)

    if args.scan:
        agent.run_scan()
    elif args.review:
        agent.run_review()
    elif args.backtest:
        from .backtesting.backtest_runner import BacktestRunner
        runner = BacktestRunner()
        for strategy in agent.strategies:
            log.info(f"Backtesting: {strategy.name}")
            result = runner.run_backtest(strategy, DEFAULT_WATCHLIST[:5])
            log.info(f"  Sharpe: {result.sharpe_ratio:.2f} | "
                     f"Return: {result.total_return:.1%} | "
                     f"MaxDD: {result.max_drawdown:.1%}")
    elif args.daemon or args.monitor:
        agent.start_scheduler()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
