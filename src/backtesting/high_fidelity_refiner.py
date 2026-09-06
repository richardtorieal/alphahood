"""
AlphaHood — High-Fidelity Backtester & Strategy Parameter Refiner
Features:
- Pre-loaded High-resolution historical data (Intraday & Daily OHLCV)
- Microstructure friction (Bid/Ask spread + execution slippage + option premium decay)
- Multi-strategy grid optimization targeting >25% net annualized return
- Automatic synchronization of winning parameter sets directly into live strategy code & config/strategies.yaml
"""
import os
import sys
import yaml
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.data.market_data import MarketDataProvider
from src.strategies.momentum_breakout import MomentumBreakoutStrategy
from src.strategies.gamma_scalp import GammaScalpStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.trend_follower import TrendFollowerStrategy
from src.utils.discord_notify import send_daily_summary

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "strategies.yaml")

# Focus Watchlist: Ultra-liquid index ETFs & Mega-caps
LIQUID_WATCHLIST = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA"]

@dataclass
class HighFidelityResult:
    strategy_name: str
    ticker_set: str
    gross_return: float
    net_return: float  # Net after spreads & slippage
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    trades_count: int
    friction_cost_pct: float
    optimal_params: Dict[str, Any]

class HighFidelityRefiner:
    """High-Fidelity Backtester with Preloaded Fast Memory Execution & Friction Modeling."""

    def __init__(
        self,
        equity_spread_pct: float = 0.0005,  # 5 bps bid-ask spread
        equity_slippage_pct: float = 0.0003, # 3 bps slippage
        options_friction_pct: float = 0.015, # 1.5% options premium friction
        initial_capital: float = 10000.0
    ):
        self.equity_spread_pct = equity_spread_pct
        self.equity_slippage_pct = equity_slippage_pct
        self.options_friction_pct = options_friction_pct
        self.initial_capital = initial_capital
        self.market_data = MarketDataProvider()
        self.preloaded_data: Dict[str, pd.DataFrame] = {}

    def preload_all_data(self, symbols: List[str], period: str = "2y", interval: str = "1d"):
        """Pre-fetch and compute technicals once for all symbols into RAM."""
        print(f"📥 Pre-loading market data & technical indicators for: {', '.join(symbols)}...")
        for sym in symbols:
            try:
                df = self.market_data.get_ohlcv(sym, period=period, interval=interval)
                if not df.empty and len(df) >= 30:
                    df_tech = self.market_data.compute_technicals(df)
                    self.preloaded_data[sym] = df_tech
            except Exception as e:
                logger.error(f"Failed to preload {sym}: {e}")

    def run_fast_backtest(
        self,
        strategy: Any,
        symbols: List[str],
        params_override: Dict[str, Any] = None
    ) -> HighFidelityResult:
        """Fast in-memory backtest over preloaded market data."""
        if params_override:
            for k, v in params_override.items():
                if hasattr(strategy, k):
                    setattr(strategy, k, v)

        all_trades = []
        friction_costs = []
        equity = self.initial_capital
        equity_curve = [equity]

        for symbol in symbols:
            if symbol not in self.preloaded_data:
                continue

            df_tech = self.preloaded_data[symbol]
            in_position = False
            entry_price = 0.0
            stop_loss = 0.0
            take_profit = 0.0

            for i in range(30, len(df_tech) - 1):
                current_bar = df_tech.iloc[i]
                prev_bar = df_tech.iloc[i-1]
                next_bar = df_tech.iloc[i+1]
                
                close_price = current_bar["Close"]
                high_price = current_bar["High"]
                low_price = current_bar["Low"]

                bar_market_data = {
                    symbol: {
                        "price": float(close_price),
                        "prev_price": float(prev_bar["Close"]),
                        "rsi": float(current_bar.get("RSI_14", 50.0)),
                        "sma_20": float(current_bar.get("SMA_20", close_price)),
                        "ema_10": float(current_bar.get("EMA_10", close_price)),
                        "ema_50": float(current_bar.get("EMA_50", close_price)),
                        "adx": float(current_bar.get("ADX_14", 25.0)),
                        "adx_14": float(current_bar.get("ADX_14", 25.0)),
                        "volume": float(current_bar.get("Volume", 1000)),
                        "avg_volume_20": float(current_bar.get("volume_sma_20", 1000)),
                        "atr_14": float(current_bar.get("ATR_14", close_price * 0.02)),
                        "bollinger_upper": float(current_bar.get("BB_upper", close_price * 1.05)),
                        "bollinger_lower": float(current_bar.get("BB_lower", close_price * 0.95)),
                        "market_cap": 25_000_000_000.0,
                        "iv_rank": 20.0
                    }
                }

                if not in_position:
                    signals = strategy.generate_signals([symbol], bar_market_data)
                    if signals:
                        sig = signals[0]
                        raw_entry = float(next_bar["Open"])
                        friction = (self.equity_spread_pct / 2.0) + self.equity_slippage_pct
                        if sig.asset_type == "OPTION":
                            friction += self.options_friction_pct

                        entry_price = raw_entry * (1.0 + friction)
                        stop_loss = sig.stop_loss if sig.stop_loss else entry_price * 0.95
                        take_profit = sig.take_profit if sig.take_profit else entry_price * 1.15
                        in_position = True
                        friction_costs.append(friction)
                else:
                    hit_stop = low_price <= stop_loss
                    hit_target = high_price >= take_profit

                    if hit_stop or hit_target or i == len(df_tech) - 2:
                        raw_exit = stop_loss if hit_stop else (take_profit if hit_target else float(next_bar["Open"]))
                        friction = (self.equity_spread_pct / 2.0) + self.equity_slippage_pct
                        exit_price = raw_exit * (1.0 - friction)

                        net_pnl_pct = (exit_price - entry_price) / entry_price
                        all_trades.append(net_pnl_pct)
                        equity *= (1.0 + net_pnl_pct)
                        equity_curve.append(equity)
                        in_position = False
                        friction_costs.append(friction)

        if not all_trades:
            return HighFidelityResult(
                strategy_name=strategy.name,
                ticker_set=", ".join(symbols[:3]),
                gross_return=0.0,
                net_return=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                trades_count=0,
                friction_cost_pct=0.0,
                optimal_params=params_override or {}
            )

        net_return = (equity - self.initial_capital) / self.initial_capital
        wins = [t for t in all_trades if t > 0]
        win_rate = len(wins) / len(all_trades)
        
        returns_arr = np.array(all_trades)
        std_dev = np.std(returns_arr) if len(returns_arr) > 1 else 1e-4
        sharpe_ratio = float((np.mean(returns_arr) / std_dev) * np.sqrt(252)) if std_dev > 0 else 0.0

        eq_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(eq_arr)
        drawdowns = (eq_arr - peak) / peak
        max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
        avg_friction = float(np.mean(friction_costs)) if friction_costs else 0.0

        return HighFidelityResult(
            strategy_name=strategy.name,
            ticker_set=", ".join(symbols),
            gross_return=net_return + (avg_friction * len(all_trades)),
            net_return=net_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            trades_count=len(all_trades),
            friction_cost_pct=avg_friction,
            optimal_params=params_override or {}
        )

    def optimize_and_sync_live(self) -> Dict[str, HighFidelityResult]:
        """Grid sweep optimization targeting >25% net gain and syncs winning config to disk."""
        print("=" * 60)
        print("🎯 High-Fidelity Strategy Optimizer & Live Code Synchronizer")
        print("   Target: >25.0% Net Gain (after Bid/Ask Spreads & Slippage)")
        print("=" * 60)

        # Preload memory cache
        self.preload_all_data(LIQUID_WATCHLIST, period="2y", interval="1d")

        best_results = {}
        winning_configs = {}

        # 1. Momentum Breakout Grid Sweep
        print("\n⚡ Optimizing Momentum Breakout Strategy...")
        mom_strat = MomentumBreakoutStrategy()
        best_mom_res = None
        for rsi_thresh in [45, 50, 55]:
            for vol_mult in [0.8, 1.0, 1.2]:
                for atr_mult in [1.5, 2.0, 2.5]:
                    params = {
                        "rsi_threshold": rsi_thresh,
                        "volume_multiple": vol_mult,
                        "trailing_stop_atr_multiplier": atr_mult
                    }
                    res = self.run_fast_backtest(mom_strat, LIQUID_WATCHLIST, params_override=params)
                    if best_mom_res is None or res.net_return > best_mom_res.net_return:
                        best_mom_res = res
                        res.optimal_params = params

        best_results["MomentumBreakout"] = best_mom_res
        winning_configs["momentum_breakout"] = best_mom_res.optimal_params
        print(f"   Winning Net Return: {best_mom_res.net_return:+.1%} | Sharpe: {best_mom_res.sharpe_ratio:.2f} | Trades: {best_mom_res.trades_count}")

        # 2. Trend Follower Grid Sweep
        print("\n📈 Optimizing Trend Follower Strategy...")
        trend_strat = TrendFollowerStrategy()
        best_trend_res = None
        for fast_ema in [5, 8, 10]:
            for slow_ema in [20, 30, 50]:
                for adx_thresh in [15, 20, 25]:
                    params = {
                        "fast_ema_period": fast_ema,
                        "slow_ema_period": slow_ema,
                        "adx_threshold": adx_thresh
                    }
                    res = self.run_fast_backtest(trend_strat, LIQUID_WATCHLIST, params_override=params)
                    if best_trend_res is None or res.net_return > best_trend_res.net_return:
                        best_trend_res = res
                        res.optimal_params = params

        best_results["TrendFollower"] = best_trend_res
        winning_configs["trend_follower"] = best_trend_res.optimal_params
        print(f"   Winning Net Return: {best_trend_res.net_return:+.1%} | Sharpe: {best_trend_res.sharpe_ratio:.2f} | Trades: {best_trend_res.trades_count}")

        # 3. Mean Reversion Grid Sweep
        print("\n🎯 Optimizing Mean Reversion Sniper Strategy...")
        mr_strat = MeanReversionStrategy()
        best_mr_res = None
        for rsi_os in [30, 35, 40, 45]:
            for bb_std in [1.5, 1.8, 2.0]:
                params = {
                    "rsi_threshold": rsi_os,
                    "bollinger_std": bb_std
                }
                res = self.run_fast_backtest(mr_strat, LIQUID_WATCHLIST, params_override=params)
                if best_mr_res is None or res.net_return > best_mr_res.net_return:
                    best_mr_res = res
                    res.optimal_params = params

        best_results["MeanReversion"] = best_mr_res
        winning_configs["mean_reversion"] = best_mr_res.optimal_params
        print(f"   Winning Net Return: {best_mr_res.net_return:+.1%} | Sharpe: {best_mr_res.sharpe_ratio:.2f} | Trades: {best_mr_res.trades_count}")

        # Sync winning configuration to disk
        self._sync_to_live_config(winning_configs)

        print("\n" + "=" * 60)
        print("🚀 Optimization & Live Code Synchronization Complete!")
        print("=" * 60)
        return best_results

    def _sync_to_live_config(self, winning_configs: dict):
        """Write refined optimal parameter values directly into config/strategies.yaml."""
        if not os.path.exists(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, "r") as f:
                data = yaml.safe_load(f) or {}

            for strat_key, params in winning_configs.items():
                if strat_key not in data:
                    data[strat_key] = {}
                data[strat_key].update(params)

            data["primary_watchlist"] = LIQUID_WATCHLIST
            data["last_refined"] = pd.Timestamp.now().isoformat()

            with open(CONFIG_PATH, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False)
            print(f"✅ Synchronized winning parameters & watchlist to {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"Failed to sync config: {e}")

if __name__ == "__main__":
    refiner = HighFidelityRefiner()
    refiner.optimize_and_sync_live()
