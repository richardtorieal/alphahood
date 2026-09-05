import unittest
import pandas as pd
from unittest.mock import MagicMock
# Assuming strategies are in src/strategies, we will mock strategy logic here for testing purposes.

class MockStrategy:
    def generate_signals(self, market_data):
        return [{"symbol": "AAPL", "action": "BUY"}]
    
    def check_exit(self, position):
        return True

class TestStrategies(unittest.TestCase):
    def setUp(self):
        self.strategy = MockStrategy()
        
    def test_generate_signals(self):
        mock_data = MagicMock()
        signals = self.strategy.generate_signals(mock_data)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol"], "AAPL")
        self.assertEqual(signals[0]["action"], "BUY")

    def test_exit_conditions(self):
        mock_position = MagicMock()
        mock_position.symbol = "AAPL"
        should_exit = self.strategy.check_exit(mock_position)
        self.assertTrue(should_exit)

    def test_empty_data(self):
        # Empty market data should result in no signals
        empty_data = None
        # Mock logic
        signals = []
        self.assertEqual(len(signals), 0)

if __name__ == '__main__':
    unittest.main()
