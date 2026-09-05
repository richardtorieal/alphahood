from dataclasses import dataclass
from typing import List, Optional
import yfinance as yf

@dataclass
class OptionChain:
    symbol: str
    expirations: List[str]

@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float

@dataclass
class OptionContract:
    symbol: str
    strike: float
    expiry: str
    contract_type: str
    last_price: float

class OptionsDataProvider:
    def get_option_chain(self, symbol: str) -> OptionChain:
        ticker = yf.Ticker(symbol)
        return OptionChain(symbol, list(ticker.options))

    def get_greeks(self, symbol: str, strike: float, expiry: str, contract_type: str) -> Greeks:
        # Mocking Greeks for now, would use py_vollib
        return Greeks(0.5, 0.05, -0.01, 0.1, 0.02)
        
    def get_iv_rank(self, symbol: str, lookback_days: int = 252) -> float:
        return 50.0  # Mock IV rank
        
    def find_optimal_contract(self, symbol: str, target_delta: float, min_dte: int, max_dte: int, contract_type: str) -> OptionContract:
        # Mock finding optimal contract
        return OptionContract(symbol, 100.0, "2024-12-20", contract_type, 2.5)
