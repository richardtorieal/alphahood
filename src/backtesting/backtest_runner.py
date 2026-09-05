import pandas as pd
from dataclasses import dataclass
from typing import List, Any
import logging

logger = logging.getLogger(__name__)

@dataclass
class BacktestResult:
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    trades_count: int

class BacktestRunner:
    def __init__(self):
        self.results = []

    def run_backtest(self, strategy: Any, symbols: List[str], start_date: str, end_date: str) -> BacktestResult:
        logger.info(f"Running backtest for {symbols} from {start_date} to {end_date}")
        
        # In a real implementation with vectorbt or backtrader, this would execute the strategy logic
        # against historical price data over the interval and return computed metrics.
        # Here we provide a completed interface layout simulating the process.
        
        simulated_return = 0.15
        simulated_sharpe = 1.2
        simulated_max_drawdown = -0.10
        simulated_win_rate = 0.55
        simulated_avg_win = 100.0
        simulated_avg_loss = 80.0
        simulated_profit_factor = 1.5
        simulated_trades_count = 150

        result = BacktestResult(
            total_return=simulated_return,
            sharpe_ratio=simulated_sharpe,
            max_drawdown=simulated_max_drawdown,
            win_rate=simulated_win_rate,
            avg_win=simulated_avg_win,
            avg_loss=simulated_avg_loss,
            profit_factor=simulated_profit_factor,
            trades_count=simulated_trades_count
        )
        self.results.append(result)
        return result

    def print_results(self, result: BacktestResult):
        print("Backtest Results:")
        print(f"Total Return: {result.total_return:.2%}")
        print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
        print(f"Max Drawdown: {result.max_drawdown:.2%}")
        print(f"Win Rate:     {result.win_rate:.2%}")
        print(f"Profit Factor:{result.profit_factor:.2f}")
        print(f"Total Trades: {result.trades_count}")
