import yfinance as yf
import pandas as pd
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class Quote:
    symbol: str
    price: float
    volume: int
    timestamp: int

class MarketDataProvider:
    def __init__(self):
        self.cache: Dict[str, dict] = {}
        self.ohlcv_cache: Dict[str, dict] = {}
        self.CACHE_TTL = 60  # seconds

    def get_ohlcv(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        now = time.time()
        cache_key = f"{symbol}_{period}_{interval}"
        if cache_key in self.ohlcv_cache and (now - self.ohlcv_cache[cache_key]['time']) < 3600:
            return self.ohlcv_cache[cache_key]['data']

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        self.ohlcv_cache[cache_key] = {'data': df, 'time': now}
        return df

    def get_current_price(self, symbol: str) -> float:
        now = time.time()
        if symbol in self.cache and now - self.cache[symbol]['time'] < self.CACHE_TTL:
            return self.cache[symbol]['price']
            
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d")
        if data.empty:
            raise ValueError(f"No data for {symbol}")
        price = data['Close'].iloc[-1]
        
        self.cache[symbol] = {'price': price, 'time': now}
        return price

    def compute_technicals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all technical indicators used by strategies."""
        df = df.copy()

        # SMAs & EMAs
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()

        # Bollinger Bands
        std_20 = df['Close'].rolling(window=20).std()
        df['BB_mid'] = df['SMA_20']
        df['BB_upper'] = df['BB_mid'] + 2 * std_20
        df['BB_lower'] = df['BB_mid'] - 2 * std_20

        # RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # ATR (14) — Average True Range
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR_14'] = true_range.rolling(window=14).mean()

        # ADX (14) — Average Directional Index
        plus_dm = df['High'].diff()
        minus_dm = -df['Low'].diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
        atr_14 = df['ATR_14']
        plus_di = 100 * (plus_dm.rolling(14).mean() / atr_14)
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr_14)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        df['ADX_14'] = dx.rolling(14).mean()

        # Volume SMA (20)
        df['volume_sma_20'] = df['Volume'].rolling(window=20).mean()

        return df

    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """Get the current ATR value for a symbol."""
        try:
            df = self.get_ohlcv(symbol, period="3mo", interval="1d")
            if df.empty or len(df) < period + 1:
                return None
            df = self.compute_technicals(df)
            atr_val = df['ATR_14'].iloc[-1]
            return float(atr_val) if pd.notna(atr_val) else None
        except Exception as e:
            logger.error(f"Failed to compute ATR for {symbol}: {e}")
            return None

    def get_batch_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """Get current quotes for multiple symbols."""
        quotes: Dict[str, Quote] = {}
        for symbol in symbols:
            try:
                price = self.get_current_price(symbol)
                quotes[symbol] = Quote(
                    symbol=symbol,
                    price=price,
                    volume=0,  # Volume not available from single-point fetch
                    timestamp=int(time.time()),
                )
            except Exception as e:
                logger.warning(f"Failed to get quote for {symbol}: {e}")
        return quotes

