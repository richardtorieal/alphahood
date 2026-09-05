# 🚀 AlphaHood

**Agentic Robinhood trading system powered by Gemini AI.**

> Cut losers fast. Let winners run. 80% options / 20% cash-or-equities.

## Overview

AlphaHood is an autonomous swing trading agent that connects to Robinhood via the official MCP (Model Context Protocol) server. It runs 4 aggressive growth strategies with full risk management, high-frequency position monitoring, and LLM-assisted trade reviews.

## Strategies

| Strategy | Type | Signal | Edge |
|---|---|---|---|
| **Momentum Breakout** | Equity + Options | RSI > 60 + SMA breakout + volume surge | Catches runners early |
| **Gamma Scalp** | Options | High gamma, near-money, 5-15 DTE, IV rank < 30 | Convex payoff on vol moves |
| **Mean Reversion** | Equity | Bollinger squeeze + RSI < 30 on quality names | Buys temporary dips |
| **Trend Follower** | Equity + Options | 10/50 EMA golden cross + ADX > 25 | Rides trends for weeks |

## Risk Management

- **Max position size**: 15% of portfolio
- **Max portfolio heat**: 40%
- **Options allocation**: Up to 80%
- **Daily loss circuit breaker**: -8%
- **All trades**: Minimum 2:1 risk/reward ratio
- **Trailing stops**: ATR-based, ratchet up only

## Dual-Frequency Monitoring

| Check | Frequency | Engine |
|---|---|---|
| Stop-loss / trailing stop | Every 5 min | Python script |
| Theta decay monitor | Every 15 min | Python script |
| LLM trade review | 2x daily (10:30 AM / 3:30 PM CT) | Gemini Flash |
| Strategy signal scan | Pre-market 8:30 AM | All strategies |
| Portfolio rebalance | Daily at close | Gemini Flash |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/yourusername/alphahood.git
cd alphahood

# 2. Install
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env with your Robinhood MCP URL, Gemini API key, Discord token

# 4. Run (paper mode)
python -m src.agent --daemon          # Full daemon with all scheduled tasks
python -m src.agent --scan            # One-time strategy scan
python -m src.agent --review          # One-time LLM trade review
python -m src.agent --backtest        # Run backtests
python -m src.agent --daemon --live   # ⚠️ Live trading (real money)
```

## Architecture

```
src/
├── agent.py              # Main orchestrator + scheduler
├── config.py             # All constants and settings
├── mcp_client.py         # Robinhood MCP integration
├── monitor.py            # High-frequency position monitor
├── trade_reviewer.py     # LLM-assisted trade analysis
├── strategies/           # Pluggable strategy modules
│   ├── base.py           # Abstract strategy interface
│   ├── momentum_breakout.py
│   ├── gamma_scalp.py
│   ├── mean_reversion.py
│   └── trend_follower.py
├── risk/                 # Risk management engine
│   ├── manager.py        # Trade validation + sizing
│   └── portfolio.py      # Portfolio state tracking
├── data/                 # Market data providers
│   ├── market_data.py    # yfinance + technicals
│   └── options_data.py   # Options chain + Greeks
├── backtesting/          # Backtesting framework
│   ├── backtest_runner.py
│   └── walk_forward.py
└── utils/                # Logging + Discord alerts
```

## Adding a New Strategy

```python
from src.strategies.base import BaseStrategy, Signal

class MyStrategy(BaseStrategy):
    name = "my_strategy"

    def generate_signals(self, symbols, market_data):
        # Your signal logic here
        return [Signal(...)]

    def should_exit(self, position, market_data):
        # Your exit logic here
        return None  # or ExitSignal(...)
```

Then add it to `AlphaHoodAgent.strategies` in `agent.py`.

## Deployment

```bash
# Docker
docker build -t alphahood .
docker run --env-file .env alphahood

# PM2
pm2 start ecosystem.config.cjs
```

## Tech Stack

- **Python 3.12+** — Core language
- **Robinhood MCP** — Official agentic trading API
- **Gemini Flash** — Dynamic model chain for trade reviews
- **yfinance** — Market data and technicals
- **VectorBT** — Fast backtesting and parameter optimization
- **Backtrader** — Walk-forward validation
- **APScheduler** — Task scheduling
- **Discord Bot API** — Trade alerts and reviews

## ⚠️ Disclaimer

This software is for educational purposes. Trading involves significant risk of loss. Always paper trade first and never risk more than you can afford to lose.

## License

MIT
