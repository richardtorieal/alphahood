import os
import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)

@dataclass
class Position:
    symbol: str
    qty: float
    average_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float

@dataclass
class OrderResult:
    order_id: str
    status: str
    symbol: str
    qty: float
    filled_qty: float
    price: Optional[float]

@dataclass
class OptionChain:
    symbol: str
    expirations: List[str]

@dataclass
class AccountInfo:
    buying_power: float
    cash: float
    equity: float

class RobinhoodMCP:
    """Robinhood MCP integration client for trading."""
    
    BASE_URL = "https://agent.robinhood.com/mcp/trading"
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 2.0

    def __init__(self):
        self.paper_mode = os.environ.get("ALPHAHOOD_PAPER_MODE", "false").lower() == "true"
        self.token = os.environ.get("ROBINHOOD_API_TOKEN", "")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        retries = 0
        while retries <= self.MAX_RETRIES:
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                logger.error(f"Request failed: {e}")
                retries += 1
                if retries <= self.MAX_RETRIES:
                    sleep_time = self.RETRY_BACKOFF_FACTOR ** retries
                    time.sleep(sleep_time)
                else:
                    raise

    def get_portfolio(self) -> AccountInfo:
        if self.paper_mode:
            return AccountInfo(10000.0, 10000.0, 10000.0)
        data = self._request("GET", "/account")
        return AccountInfo(**data)

    def get_positions(self) -> List[Position]:
        if self.paper_mode:
            return []
        data = self._request("GET", "/positions")
        return [Position(**p) for p in data.get("positions", [])]

    def place_equity_order(self, symbol: str, side: str, qty: float, order_type: str, limit_price: Optional[float] = None) -> OrderResult:
        logger.info(f"Placing equity order: {symbol} {side} {qty} {order_type} {limit_price}")
        if self.paper_mode:
            return OrderResult("paper-123", "filled", symbol, qty, qty, limit_price or 100.0)
        
        payload = {
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "type": order_type,
            "price": limit_price
        }
        data = self._request("POST", "/orders", json=payload)
        return OrderResult(**data)

    def cancel_order(self, order_id: str) -> bool:
        if self.paper_mode:
            return True
        self._request("DELETE", f"/orders/{order_id}")
        return True
