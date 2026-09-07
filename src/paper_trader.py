import os
import json
import logging
import argparse
import time
from datetime import datetime, timedelta, time as datetime_time
from typing import Dict, Any, List, Optional
import sys
import yfinance as yf
import pandas as pd
import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.market_data import MarketDataProvider
from src.strategies.trend_follower import TrendFollowerStrategy
from src.strategies.momentum_breakout import MomentumBreakoutStrategy

# Fallback for call_mcp_tool if not provided in environment
def call_mcp_tool(server: str, tool: str, **kwargs) -> Any:
    # This function is expected to be intercepted or provided by the environment.
    logging.warning(f"Mock call_mcp_tool: {server} -> {tool} with args {kwargs}")
    return {}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), '../data/paper_trader.log'))
    ]
)
logger = logging.getLogger("PaperTrader")

# Primary watchlist for paper trading
PAPER_WATCHLIST = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA"]
INITIAL_CAPITAL = 500.0
CONTRACT_FEE = 0.65
STOP_LOSS_PCT = 0.75  # -25% stop loss on premium
TRAILING_TRIGGER_PCT = 1.20  # +20% gain triggers trailing stop
TRAILING_LOCK_PCT = 0.85  # Lock 85% of peak premium
MOMENTUM_DTE_FLOOR = 3  # Hold to 3 DTE if strong momentum
WEAK_DTE_EXIT = 10  # Exit at 10 DTE if momentum is weak


class PaperTrader:
    def __init__(self, mode: str):
        self.mode = mode
        self.data_dir = os.path.join(os.path.dirname(__file__), '../data')
        self.reports_dir = os.path.join(self.data_dir, 'paper_reports')
        self.portfolio_file = os.path.join(self.data_dir, 'paper_portfolio.json')
        
        os.makedirs(self.reports_dir, exist_ok=True)
        
        self.portfolio = self._load_portfolio()
        self.market_data = MarketDataProvider()
        self.strategies = [
            TrendFollowerStrategy(),
            MomentumBreakoutStrategy(),
        ]
        
    def _load_portfolio(self) -> Dict[str, Any]:
        if os.path.exists(self.portfolio_file):
            with open(self.portfolio_file, 'r') as f:
                return json.load(f)
        return {
            "cash": 500.0,
            "positions": [],
            "history": []
        }
        
    def _save_portfolio(self):
        with open(self.portfolio_file, 'w') as f:
            json.dump(self.portfolio, f, indent=4)
            
    def _discord_notify(self, message: str):
        call_mcp_tool("discord", "discord_send", channelId="1484082460668203102", content=message)
        
    def start(self):
        logger.info(f"Starting Paper Trader in {self.mode} mode.")
        self._discord_notify(f"🚀 Paper Trader started in {self.mode} mode. Starting balance: ${self.portfolio['cash']:.2f}")
        
        scheduler = BlockingScheduler()
        
        # Self-Monitoring Loop every 5 mins from 9:30 AM to 4:00 PM Eastern
        # Since APScheduler uses local time by default, we'll assume the environment is set up.
        # Note: timezone handling should be careful. We'll use cron.
        scheduler.add_job(
            self.monitor_positions,
            'cron',
            day_of_week='mon-fri',
            hour='9-15',
            minute='*/5'
        )
        # To handle 16:00 exactly
        scheduler.add_job(
            self.monitor_positions,
            'cron',
            day_of_week='mon-fri',
            hour='16',
            minute='0'
        )
        
        # End of day report
        scheduler.add_job(
            self.generate_daily_report,
            'cron',
            day_of_week='mon-fri',
            hour='16',
            minute='5'
        )

        # Strategy scan at 9:35 AM (5 min after open, let spreads settle)
        scheduler.add_job(
            self.run_strategy_scan,
            'cron',
            day_of_week='mon-fri',
            hour='9',
            minute='35'
        )
        
        scheduler.start()

    def get_technical_indicators(self, symbol: str) -> Dict[str, float]:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="3mo", interval="1d")
        if df.empty:
            return {}
        
        # Calculate EMA 10 and 50
        df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        
        # Calculate RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # Calculate ADX (simplified using ATR and DM)
        high = df['High']
        low = df['Low']
        close = df['Close']
        plus_dm = high.diff()
        minus_dm = low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        
        tr1 = pd.DataFrame(high - low)
        tr2 = pd.DataFrame(abs(high - close.shift(1)))
        tr3 = pd.DataFrame(abs(low - close.shift(1)))
        frames = [tr1, tr2, tr3]
        tr = pd.concat(frames, axis=1, join='inner').max(axis=1)
        atr = tr.rolling(14).mean()
        
        plus_di = 100 * (plus_dm.ewm(alpha=1/14).mean() / atr)
        minus_di = 100 * (abs(minus_dm).ewm(alpha=1/14).mean() / atr)
        dx = (abs(plus_di - minus_di) / abs(plus_di + minus_di)) * 100
        adx = dx.ewm(alpha=1/14).mean()
        
        df['ADX'] = adx
        
        latest = df.iloc[-1]
        return {
            "EMA_10": latest['EMA_10'],
            "EMA_50": latest['EMA_50'],
            "RSI": latest['RSI'],
            "ADX": latest['ADX']
        }

    def monitor_positions(self):
        logger.info("Running monitor loop...")
        for pos in self.portfolio['positions']:
            self._evaluate_position(pos)
            
        self._save_portfolio()
            
    def _evaluate_position(self, pos: Dict[str, Any]):
        symbol = pos['symbol']
        # Fetch real option quote
        try:
            # Assuming get_option_quotes returns a dict with bid/ask
            quote_data = call_mcp_tool('robinhood', 'get_option_quotes', instruments=[pos['instrument_id']])
            if not quote_data or 'results' not in quote_data or not quote_data['results']:
                return
            quote = quote_data['results'][0]
            current_bid = float(quote['bid_price'])
            current_ask = float(quote['ask_price'])
            
            # Update position value
            current_value = current_bid * 100 * pos['contracts']
            pos['current_value'] = current_value
            unrealized_pnl = current_value - pos['cost_basis']
            pos['unrealized_pnl'] = unrealized_pnl
            
            current_premium = current_bid
            entry_premium = pos['entry_price']
            
            # Peak premium tracking for trailing stop
            if 'peak_premium' not in pos:
                pos['peak_premium'] = entry_premium
            pos['peak_premium'] = max(pos['peak_premium'], current_premium)
            
            # Check Exit Conditions
            exit_reason = None
            
            # 1. Stop loss -25%
            if current_premium <= entry_premium * 0.75:
                exit_reason = "Stop Loss (-25%)"
                
            # 2. Trailing stop (+20% gain triggers it at 85% of peak)
            elif pos['peak_premium'] >= entry_premium * 1.20:
                if current_premium <= pos['peak_premium'] * 0.85:
                    exit_reason = "Trailing Stop Triggered"
                    
            # Fetch underlying technicals
            techs = self.get_technical_indicators(symbol)
            if not techs:
                return
                
            # 3. Death Cross
            if techs['EMA_10'] < techs['EMA_50']:
                exit_reason = "Death Cross (EMA 10 < 50)"
                
            # 4. Momentum-aware DTE exit
            expiry = datetime.strptime(pos['expiration'], "%Y-%m-%d")
            dte = (expiry - datetime.now()).days
            
            momentum_strong = techs['RSI'] > 55 or (techs['EMA_10'] > techs['EMA_50'] and techs['ADX'] > 20)
            
            if dte <= 3 and momentum_strong:
                exit_reason = "DTE <= 3 (Momentum Exit)"
            elif dte <= 10 and not momentum_strong:
                exit_reason = "DTE <= 10 (Weak Momentum Exit)"
                
            if exit_reason:
                self.close_position(pos, exit_reason, current_premium)
                
        except Exception as e:
            logger.error(f"Error evaluating position {pos['symbol']}: {e}")
            
    def close_position(self, pos: Dict[str, Any], reason: str, exit_price: float):
        if self.mode == "manual-approval":
            logger.info(f"Manual approval required to close {pos['symbol']} due to {reason}")
            # In a real app, this would block or wait for user input
            return
            
        logger.info(f"Closing position {pos['symbol']} - Reason: {reason}")
        contracts = pos['contracts']
        revenue = exit_price * 100 * contracts
        fees = 0.65 * contracts
        net_revenue = revenue - fees
        
        self.portfolio['cash'] += net_revenue
        
        pnl = net_revenue - pos['cost_basis']
        
        trade_record = {
            "symbol": pos['symbol'],
            "contract_type": pos['contract_type'],
            "strike": pos['strike'],
            "expiration": pos['expiration'],
            "entry_price": pos['entry_price'],
            "entry_timestamp": pos['entry_timestamp'],
            "exit_price": exit_price,
            "exit_timestamp": datetime.now().isoformat(),
            "contracts": contracts,
            "pnl": pnl,
            "reason": reason,
            "strategy_name": pos.get('strategy_name', 'unknown')
        }
        
        self.portfolio['history'].append(trade_record)
        self.portfolio['positions'].remove(pos)
        self._save_portfolio()
        
        self._discord_notify(f"Trade Closed: {pos['symbol']} {pos['strike']} {pos['contract_type']}\nReason: {reason}\nNet PnL: ${pnl:.2f}")

    def run_strategy_scan(self):
        """Run all strategies against the watchlist and paper-execute approved signals."""
        logger.info(f"📡 Running strategy scan across {len(PAPER_WATCHLIST)} symbols...")
        
        # Fetch live market data for all watchlist symbols
        bar_data = {}
        for symbol in PAPER_WATCHLIST:
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="3mo", interval="1d")
                if df.empty or len(df) < 30:
                    continue
                df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
                df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
                delta = df['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                df['RSI_14'] = 100 - (100 / (1 + rs))
                df['SMA_20'] = df['Close'].rolling(20).mean()
                df['ATR_14'] = (df['High'] - df['Low']).rolling(14).mean()
                
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                bar_data[symbol] = {
                    "price": float(latest['Close']),
                    "prev_price": float(prev['Close']),
                    "rsi": float(latest.get('RSI_14', 50.0)),
                    "sma_20": float(latest.get('SMA_20', latest['Close'])),
                    "ema_10": float(latest.get('EMA_10', latest['Close'])),
                    "ema_50": float(latest.get('EMA_50', latest['Close'])),
                    "adx": 25.0,  # Simplified; full ADX from get_technical_indicators
                    "adx_14": 25.0,
                    "volume": float(latest.get('Volume', 1000)),
                    "avg_volume_20": float(latest.get('Volume', 1000)),
                    "atr_14": float(latest.get('ATR_14', latest['Close'] * 0.02)),
                    "bollinger_upper": float(latest['Close'] * 1.05),
                    "bollinger_lower": float(latest['Close'] * 0.95),
                    "market_cap": 25_000_000_000.0,
                    "iv_rank": 20.0,
                }
            except Exception as e:
                logger.error(f"Error fetching data for {symbol}: {e}")
        
        # Run strategies
        max_positions = 2
        current_positions = len(self.portfolio['positions'])
        
        for strategy in self.strategies:
            if current_positions >= max_positions:
                break
            for symbol in PAPER_WATCHLIST:
                if current_positions >= max_positions:
                    break
                if symbol not in bar_data:
                    continue
                # Skip if already holding this symbol
                if any(p['symbol'] == symbol for p in self.portfolio['positions']):
                    continue
                
                signals = strategy.generate_signals([symbol], {symbol: bar_data[symbol]})
                if signals:
                    sig = signals[0]
                    price = bar_data[symbol]['price']
                    strike = round(price * 1.02, 0)  # 2% OTM call
                    # Find nearest Friday expiration ~25 DTE out
                    from datetime import date, timedelta
                    target_date = date.today() + timedelta(days=25)
                    # Round to next Friday
                    days_ahead = 4 - target_date.weekday()  # Friday = 4
                    if days_ahead <= 0:
                        days_ahead += 7
                    expiry_date = target_date + timedelta(days=days_ahead)
                    expiration = expiry_date.strftime("%Y-%m-%d")
                    
                    logger.info(f"📈 Signal: {symbol} {strike}C exp {expiration} from {strategy.name}")
                    self.on_strategy_signal(
                        symbol=symbol,
                        contract_type="CALL",
                        strike=strike,
                        expiration=expiration,
                        strategy_name=strategy.name,
                        contracts=1
                    )
                    current_positions += 1
        
    def generate_daily_report(self):
        logger.info("Generating daily report...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        today_trades = [t for t in self.portfolio['history'] if t['exit_timestamp'].startswith(today_str)]
        
        total_pnl = sum(t['pnl'] for t in today_trades)
        wins = [t for t in today_trades if t['pnl'] > 0]
        losses = [t for t in today_trades if t['pnl'] <= 0]
        
        report = {
            "date": today_str,
            "total_pnl": total_pnl,
            "win_count": len(wins),
            "loss_count": len(losses),
            "best_trade": max(today_trades, key=lambda x: x['pnl']) if wins else None,
            "worst_trade": min(today_trades, key=lambda x: x['pnl']) if losses else None,
            "strategy_breakdown": {},
            "mistakes_detected": []
        }
        
        for t in today_trades:
            s = t['strategy_name']
            if s not in report['strategy_breakdown']:
                report['strategy_breakdown'][s] = 0
            report['strategy_breakdown'][s] += t['pnl']
            
            # Mistake detection logic
            entry_time = datetime.fromisoformat(t['entry_timestamp'])
            exit_time = datetime.fromisoformat(t['exit_timestamp'])
            days_held = (exit_time - entry_time).days
            
            if t['reason'] == "Stop Loss (-25%)" and days_held <= 1:
                report['mistakes_detected'].append(f"{t['symbol']}: Hit stop loss within 1 day (possible false signal)")
                
            if t['reason'] == "Trailing Stop Triggered" and t['pnl'] < 0:
                report['mistakes_detected'].append(f"{t['symbol']}: Exited on trailing stop but still lost money")
                
            if "Momentum Exit" in t['reason'] and t['pnl'] < 0:
                report['mistakes_detected'].append(f"{t['symbol']}: Held for momentum exit but resulted in a loss")
                
        report_path = os.path.join(self.reports_dir, f"{today_str}.json")
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=4)
            
        refinements = {
            "date": today_str,
            "suggested_changes": []
        }
        if len(losses) > len(wins):
            refinements['suggested_changes'].append("Consider tightening stop loss to -20%.")
            
        refinement_path = os.path.join(self.reports_dir, f"{today_str}_refinements.json")
        with open(refinement_path, 'w') as f:
            json.dump(refinements, f, indent=4)
            
        summary_msg = f"📊 Daily Report for {today_str}\nTotal PnL: ${total_pnl:.2f}\nWins: {len(wins)} | Losses: {len(losses)}"
        self._discord_notify(summary_msg)
        
        logger.info(f"Daily report saved to {report_path}")

    def on_strategy_signal(self, symbol: str, contract_type: str, strike: float, expiration: str, strategy_name: str, contracts: int = 1):
        """Simulate a BUY_TO_OPEN trade."""
        if self.mode == "manual-approval":
            logger.info(f"Manual approval required to open {contracts} {symbol} {contract_type} {strike}")
            # wait for user input in real app
            return
            
        try:
            # Note: For real use, we'd find the exact instrument_id using get_option_instruments
            # For demonstration, we assume we fetch the quote by symbol, strike, etc.
            # Using Robinhood MCP to get the chain and quotes.
            quote_data = call_mcp_tool('robinhood', 'get_option_quotes', instruments=[f"{symbol}_{strike}_{expiration}_{contract_type}"])
            if not quote_data or 'results' not in quote_data or not quote_data['results']:
                logger.error("Could not fetch quote for signal.")
                return
            
            quote = quote_data['results'][0]
            current_ask = float(quote['ask_price'])
            
            cost = current_ask * 100 * contracts
            fees = 0.65 * contracts
            total_cost = cost + fees
            
            if self.portfolio['cash'] < total_cost:
                logger.warning(f"Insufficient funds for {symbol} trade. Need ${total_cost:.2f}, have ${self.portfolio['cash']:.2f}")
                return
                
            self.portfolio['cash'] -= total_cost
            
            position = {
                "symbol": symbol,
                "contract_type": contract_type,
                "strike": strike,
                "expiration": expiration,
                "entry_price": current_ask,
                "entry_timestamp": datetime.now().isoformat(),
                "contracts": contracts,
                "cost_basis": total_cost,
                "current_value": cost,
                "unrealized_pnl": -fees,
                "strategy_name": strategy_name,
                "instrument_id": f"{symbol}_{strike}_{expiration}_{contract_type}",
                "peak_premium": current_ask
            }
            
            self.portfolio['positions'].append(position)
            self._save_portfolio()
            
            msg = f"Trade Opened: {symbol} {strike} {contract_type} @ ${current_ask:.2f}\nCost: ${total_cost:.2f}"
            self._discord_notify(msg)
            logger.info(msg)
            
        except Exception as e:
            logger.error(f"Error simulating signal: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AlphaHood Paper Trader")
    parser.add_argument("--mode", choices=["shadow", "manual-approval"], default="shadow", help="Trading mode")
    args = parser.parse_args()
    
    trader = PaperTrader(mode=args.mode)
    trader.start()
