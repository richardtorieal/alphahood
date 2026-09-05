"""
Centralized configuration for AlphaHood.
"""

import os
from typing import Any
import yaml

# Risk Parameters (AGGRESSIVE)
MAX_POSITION_SIZE_PCT = 0.15
MAX_PORTFOLIO_HEAT = 0.40
STOP_LOSS_PCT_MIN = -0.05
STOP_LOSS_PCT_MAX = -0.03
MAX_CONCURRENT_POSITIONS = 10
DAILY_LOSS_LIMIT = -0.08
MAX_OPTIONS_ALLOCATION = 0.80
MIN_CASH_EQUITY_RESERVE = 0.20
MIN_RISK_REWARD_RATIO = 2.0

# Trading hours constants (CT)
MARKET_OPEN_HOUR = 8
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 0

# Monitoring schedules
MONITOR_INTERVAL_SECONDS = 300  # 5 minutes
THETA_CHECK_INTERVAL_SECONDS = 900  # 15 minutes (alias)
THETA_CHECK_SECONDS = THETA_CHECK_INTERVAL_SECONDS
LLM_REVIEW_TIMES = ['10:30', '15:30']  # 10:30 AM and 3:30 PM CT
STRATEGY_SCAN_TIME = '08:30'  # Pre-market scan time CT

# Aliases for clearer imports across modules
MAX_OPTIONS_ALLOCATION_PCT = MAX_OPTIONS_ALLOCATION
STOP_LOSS_HARD_PCT = STOP_LOSS_PCT_MIN  # -5% hard stop
DAILY_LOSS_LIMIT_PCT = DAILY_LOSS_LIMIT  # -8% circuit breaker

# Environment Variables
ROBINHOOD_MCP_URL = os.getenv("ROBINHOOD_MCP_URL", "http://localhost:8000")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")

# Load Strategy Config
def load_strategy_config(file_path: str = "config/strategies.yaml") -> dict[str, Any]:
    """Loads strategy configuration from a YAML file."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.join(base_dir, file_path)
        with open(full_path, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Warning: Failed to load strategy config, using defaults. Error: {e}")
        return {}

STRATEGY_CONFIG = load_strategy_config()

def get_strategy_param(strategy: str, param: str, default: Any) -> Any:
    """Helper to get a strategy parameter with a fallback default."""
    return STRATEGY_CONFIG.get(strategy, {}).get(param, default)
