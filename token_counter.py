"""
Module for handling token counting operations with caching.
"""
import tiktoken
from functools import lru_cache

class TokenCounter:
    """Efficient token counting with model encoding caching."""
    
    @staticmethod
    @lru_cache(maxsize=8)
    def _get_encoding(model: str) -> tiktoken.Encoding:
        """Get cached encoding for a model."""
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")
    
    @classmethod
    def count_tokens(cls, text: str, model: str = "gpt-3.5-turbo") -> int:
        """Count tokens in text for specified model."""
        if not text:
            return 0
        encoding = cls._get_encoding(model)
        return len(encoding.encode(text))
