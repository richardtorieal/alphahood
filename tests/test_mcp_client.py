import unittest
from unittest.mock import patch, MagicMock
import os
from src.mcp_client import RobinhoodMCP, AccountInfo, Position

class TestMCPClient(unittest.TestCase):
    def setUp(self):
        os.environ["ALPHAHOOD_PAPER_MODE"] = "true"
        self.client = RobinhoodMCP()

    def test_paper_mode_portfolio(self):
        portfolio = self.client.get_portfolio()
        self.assertIsInstance(portfolio, AccountInfo)
        self.assertEqual(portfolio.buying_power, 10000.0)

    def test_paper_mode_positions(self):
        positions = self.client.get_positions()
        self.assertEqual(positions, [])

    def test_paper_mode_place_order(self):
        order = self.client.place_equity_order("AAPL", "buy", 10, "market")
        self.assertEqual(order.status, "filled")
        self.assertEqual(order.qty, 10)

    def test_paper_mode_cancel_order(self):
        success = self.client.cancel_order("paper-123")
        self.assertTrue(success)

    @patch('src.mcp_client.requests.Session.request')
    def test_retry_logic(self, mock_request):
        os.environ["ALPHAHOOD_PAPER_MODE"] = "false"
        client = RobinhoodMCP()
        
        # Setup mock to fail twice, then succeed
        from requests.exceptions import RequestException
        mock_response = MagicMock()
        mock_response.json.return_value = {"buying_power": 100, "cash": 100, "equity": 100}
        mock_response.raise_for_status = MagicMock()
        
        mock_request.side_effect = [RequestException("Network Error"), RequestException("Network Error"), mock_response]
        
        # Override sleep for fast testing
        with patch('time.sleep', return_value=None):
            portfolio = client.get_portfolio()
            
        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(portfolio.buying_power, 100)

if __name__ == '__main__':
    unittest.main()
