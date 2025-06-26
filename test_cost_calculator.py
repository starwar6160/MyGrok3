"""
Tests for cost calculation functionality.
"""
import unittest
from unittest.mock import patch, MagicMock
from cost_calculator import PriceManager, estimate_cost, initialize_prices

class TestPriceManager(unittest.TestCase):
    def setUp(self):
        self.price_data = {
            "gpt-4": {"input": 10.0, "output": 30.0},
            "gpt-3.5-turbo": {"input": 1.5, "output": 2.0}
        }
        self.manager = PriceManager()
        self.manager.update_prices(self.price_data)
    
    def test_get_model_price(self):
        """Test getting prices for known and unknown models."""
        self.assertEqual(self.manager.get_model_price("gpt-4"), {"input": 10.0, "output": 30.0})
        self.assertEqual(self.manager.get_model_price("unknown"), {"input": 0, "output": 0})
    
    def test_price_caching(self):
        """Test that prices are properly cached."""
        self.manager.get_model_price("gpt-4")
        self.manager._price_data["gpt-4"] = {"input": 20.0, "output": 40.0}
        # Should still return cached price
        self.assertEqual(self.manager.get_model_price("gpt-4"), {"input": 10.0, "output": 30.0})
        
    def test_update_prices(self):
        """Test that price updates clear the cache."""
        new_prices = {"gpt-4": {"input": 20.0, "output": 40.0}}
        self.manager.update_prices(new_prices)
        self.assertEqual(self.manager.get_model_price("gpt-4"), {"input": 20.0, "output": 40.0})

class TestCostEstimation(unittest.TestCase):
    @patch('MyGrok3.cost_calculator.price_manager')
    def test_estimate_cost(self, mock_manager):
        """Test cost estimation calculations."""
        mock_manager.get_model_price.return_value = {"input": 10.0, "output": 30.0}
        
        # Test with 1M input tokens, 500K output tokens
        cost = estimate_cost("gpt-4", 1_000_000, 500_000)
        self.assertEqual(cost, 10.0 + 15.0)  # $10 + $15
        
    @patch('MyGrok3.cost_calculator.price_manager')
    def test_initialize_prices(self, mock_manager):
        """Test price initialization."""
        test_prices = {"test-model": {"input": 5.0, "output": 10.0}}
        initialize_prices()
        mock_manager.update_prices.assert_called_once()

if __name__ == '__main__':
    unittest.main()
