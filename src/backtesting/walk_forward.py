import pandas as pd
from typing import List, Dict, Tuple
from .backtest_runner import BacktestRunner, BacktestResult

class WalkForwardValidator:
    def __init__(self):
        self.runner = BacktestRunner()

    def generate_windows(self, start_date: str, end_date: str, is_months: int = 6, oos_months: int = 2) -> List[Dict[str, str]]:
        windows = []
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        
        current_is_start = start_ts
        while True:
            current_is_end = current_is_start + pd.DateOffset(months=is_months)
            current_oos_end = current_is_end + pd.DateOffset(months=oos_months)
            
            if current_oos_end > end_ts:
                break
                
            windows.append({
                "is_start": current_is_start.strftime("%Y-%m-%d"),
                "is_end": current_is_end.strftime("%Y-%m-%d"),
                "oos_start": current_is_end.strftime("%Y-%m-%d"),
                "oos_end": current_oos_end.strftime("%Y-%m-%d")
            })
            
            current_is_start = current_is_start + pd.DateOffset(months=oos_months)
            
        return windows

    def run_validation(self, strategy: any, symbols: List[str], start_date: str, end_date: str) -> Dict[str, List[BacktestResult]]:
        windows = self.generate_windows(start_date, end_date)
        is_results = []
        oos_results = []
        
        for w in windows:
            # Run In-Sample
            is_result = self.runner.run_backtest(strategy, symbols, w["is_start"], w["is_end"])
            is_results.append(is_result)
            
            # Run Out-Of-Sample
            oos_result = self.runner.run_backtest(strategy, symbols, w["oos_start"], w["oos_end"])
            oos_results.append(oos_result)
            
        return {
            "in_sample": is_results,
            "out_of_sample": oos_results
        }

    def calculate_degradation(self, is_result: BacktestResult, oos_result: BacktestResult) -> float:
        # Lower is better; 0 means no degradation.
        if is_result.sharpe_ratio == 0:
            return 0.0
        return (is_result.sharpe_ratio - oos_result.sharpe_ratio) / is_result.sharpe_ratio
