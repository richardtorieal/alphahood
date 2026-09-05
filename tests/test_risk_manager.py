import unittest

class MockRiskManager:
    def calculate_position_size(self, account_value, risk_per_trade, stop_loss_pct):
        return (account_value * risk_per_trade) / stop_loss_pct

    def check_portfolio_heat(self, current_heat, new_trade_heat, max_heat=0.2):
        return (current_heat + new_trade_heat) <= max_heat

    def check_daily_loss(self, start_balance, current_balance, max_loss_pct=0.05):
        return ((start_balance - current_balance) / start_balance) < max_loss_pct

    def check_options_allocation(self, current_options, new_option, max_allocation):
        return (current_options + new_option) <= max_allocation

    def check_concurrent_positions(self, current_count, max_count=5):
        return current_count < max_count

class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.rm = MockRiskManager()

    def test_position_sizing(self):
        size = self.rm.calculate_position_size(10000, 0.01, 0.05)
        self.assertEqual(size, 2000)

    def test_portfolio_heat_limits(self):
        self.assertTrue(self.rm.check_portfolio_heat(0.1, 0.05))
        self.assertFalse(self.rm.check_portfolio_heat(0.15, 0.10))

    def test_daily_loss_circuit_breaker(self):
        self.assertTrue(self.rm.check_daily_loss(10000, 9600))
        self.assertFalse(self.rm.check_daily_loss(10000, 9400))

    def test_options_allocation_limits(self):
        self.assertTrue(self.rm.check_options_allocation(1000, 500, 2000))
        self.assertFalse(self.rm.check_options_allocation(1800, 300, 2000))

    def test_concurrent_position_limits(self):
        self.assertTrue(self.rm.check_concurrent_positions(4))
        self.assertFalse(self.rm.check_concurrent_positions(5))

if __name__ == '__main__':
    unittest.main()
