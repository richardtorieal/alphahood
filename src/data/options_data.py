import os
from dataclasses import dataclass
from typing import List, Optional, Dict
import pandas as pd
import numpy as np
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

class OptionsDXParser:
    """Parses and provides lookup for OptionsDX EOD CSV data."""
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'optionsdx')
        else:
            self.data_dir = data_dir
        
        self.data: Dict[str, pd.DataFrame] = {}
        self.loaded = False

    def load_data(self):
        """Loads all CSV files in the data directory."""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
            return

        files = [f for f in os.listdir(self.data_dir) if f.endswith('.csv')]
        if not files:
            return

        dfs = []
        for f in files:
            path = os.path.join(self.data_dir, f)
            df = pd.read_csv(path)
            # Standardize column names if needed. Expecting:
            # [QUOTE_DATE, EXPIRE_DATE, STRIKE, C_BID, C_ASK, C_DELTA, P_BID, P_ASK, P_DELTA, UNDERLYING_LAST]
            df['QUOTE_DATE'] = pd.to_datetime(df['QUOTE_DATE'])
            df['EXPIRE_DATE'] = pd.to_datetime(df['EXPIRE_DATE'])
            dfs.append(df)
            
        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            # Group by symbol if multiple symbols exist, but OptionsDX usually is one symbol per file (e.g. SPY)
            # Assuming the user names files or there's a symbol column. If no symbol column, we infer from filename.
            # But let's assume the user uses SPY_*.csv
            for f in files:
                symbol = f.split('_')[0].upper()
                if symbol not in self.data:
                    self.data[symbol] = combined # Simplified: assumes single file/symbol for now or combined has everything
            self.loaded = True

    def get_historical_options(self, symbol: str, quote_date: pd.Timestamp) -> pd.DataFrame:
        if symbol not in self.data:
            return pd.DataFrame()
            
        df = self.data[symbol]
        # Filter for exact date
        # Note: quote_date might not perfectly match if times are included, ensure normalized dates
        mask = df['QUOTE_DATE'].dt.normalize() == quote_date.normalize()
        return df[mask]

    def get_premium(self, symbol: str, quote_date: pd.Timestamp, strike: float, contract_type: str = "CALL", target_dte: int = None) -> Optional[float]:
        df_day = self.get_historical_options(symbol, quote_date)
        if df_day.empty:
            return None
            
        # Find exact strike
        df_strike = df_day[np.isclose(df_day['STRIKE'], strike, atol=0.01)]
        if df_strike.empty:
            return None
            
        if target_dte is not None:
            # Find closest expiration
            df_strike['DTE'] = (df_strike['EXPIRE_DATE'] - quote_date).dt.days
            df_strike = df_strike.iloc[(df_strike['DTE'] - target_dte).abs().argsort()[:1]]
            
        if df_strike.empty:
            return None
            
        row = df_strike.iloc[0]
        if contract_type.upper() == "CALL":
            bid = row.get('C_BID', 0)
            ask = row.get('C_ASK', 0)
        else:
            bid = row.get('P_BID', 0)
            ask = row.get('P_ASK', 0)
            
        # Use midpoint or ask for conservative entry
        return (bid + ask) / 2.0 if bid > 0 and ask > 0 else None
