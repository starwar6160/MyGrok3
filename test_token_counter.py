"""
Tests for token counting functionality.
"""
import unittest
from token_counter import TokenCounter

class TestTokenCounter(unittest.TestCase):
    def test_count_tokens(self):
        """Test basic token counting."""
        self.assertEqual(TokenCounter.count_tokens("hello world"), 2)
        self.assertEqual(TokenCounter.count_tokens("", "gpt-4"), 0)
        
    def test_model_specific_encoding(self):
        """Test different model encodings."""
        text = "hello world"
        gpt3_count = TokenCounter.count_tokens(text, "gpt-3.5-turbo")
        gpt4_count = TokenCounter.count_tokens(text, "gpt-4")
        self.assertEqual(gpt3_count, gpt4_count)  # Same encoding
        
    def test_unknown_model_fallback(self):
        """Test fallback for unknown models."""
        text = "hello world"
        known_count = TokenCounter.count_tokens(text, "gpt-3.5-turbo")
        unknown_count = TokenCounter.count_tokens(text, "unknown-model")
        self.assertEqual(known_count, unknown_count)

if __name__ == '__main__':
    unittest.main()
