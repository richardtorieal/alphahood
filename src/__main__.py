"""AlphaHood Paper Trader - Module entry point."""
from src.paper_trader import PaperTrader
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AlphaHood Paper Trader")
    parser.add_argument("--mode", choices=["shadow", "manual-approval"], default="shadow", help="Trading mode")
    args = parser.parse_args()

    trader = PaperTrader(mode=args.mode)
    trader.start()
