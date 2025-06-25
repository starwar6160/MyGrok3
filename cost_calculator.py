"""
Module for handling cost calculations and token tracking with improved structure.
"""
from typing import Optional, Dict
from MyGrok3 import logging_config
import logging

# Get configured logger
logger = logging_config.configure_logger(__name__)

class CostTracker:
    """Track token usage and costs across requests."""
    
    def __init__(self):
        self._input_tokens = 0
        self._output_tokens = 0
        self._cumulative_cost = 0.0
        self._model_name = None
    
    @property
    def input_tokens(self) -> int:
        """Get the current input token count."""
        return self._input_tokens
    
    @property
    def output_tokens(self) -> int:
        """Get the current output token count."""
        return self._output_tokens
    
    @property
    def cumulative_cost(self) -> float:
        """Get the current cumulative cost."""
        return self._cumulative_cost
    
    def update(self, input_tokens: int = 0, output_tokens: int = 0, cost: float = 0.0) -> None:
        """Update token counts and cost with validation.
        
        Args:
            input_tokens: Number of input tokens to add
            output_tokens: Number of output tokens to add
            cost: Cost to add to the cumulative total
        """
        if cost < 0:
            logger.warning(f"Negative cost detected: {cost}, ignoring")
            return
            
        new_cumulative = self._cumulative_cost + cost
        if new_cumulative < self._cumulative_cost:
            logger.error(f"Cost would decrease from {self._cumulative_cost} to {new_cumulative}")
            return
            
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._cumulative_cost = new_cumulative
    
    def get_diagnostic_info(self, model_name: str = None, input_text: str = None, 
                         output_text: str = None, is_debug: bool = False) -> str:
        """Generate formatted diagnostic information.
        
        Args:
            model_name: Name of the model being used (optional)
            input_text: Optional input text (for debug purposes)
            output_text: Optional output text (for debug purposes)
            is_debug: Whether to include additional debug information
            
        Returns:
            str: Formatted diagnostic string with token counts and cost
        """
        try:
            # Use provided model name or fall back to stored one
            display_model = model_name or self._model_name or "unknown"
            
            # Format the base information
            base_info = (
                f"|Model: {display_model} | "
                f"Tokens: {self._input_tokens}i/{self._output_tokens}o | "
                f"Cost: ${self._cumulative_cost:.6f}"
            )
            
            # Add debug information if requested
            if is_debug:
                debug_info = []
                if input_text is not None:
                    input_sample = input_text[:50] + '...' if len(input_text) > 50 else input_text
                    debug_info.append(f"Input: '{input_sample}'")
                if output_text is not None:
                    output_sample = output_text[:50] + '...' if len(output_text) > 50 else output_text
                    debug_info.append(f"Output: '{output_sample}'")
                
                if debug_info:
                    base_info = f"{base_info} | {' | '.join(debug_info)}"
            
            return base_info
            
        except Exception as e:
            logger.error(f"Failed to generate diagnostics: {e}")
            return f"|Error generating diagnostics: {str(e)}|"


from functools import lru_cache

class PriceManager:
    """Manage and cache model pricing information."""
    
    def __init__(self, price_data: Optional[Dict] = None):
        self._price_data = price_data or {}
    
    @lru_cache(maxsize=32)
    def get_model_price(self, model_name: str) -> Dict[str, float]:
        """Get pricing info for a model with caching."""
        return self._price_data.get(model_name, {'input': 0, 'output': 0})
    
    def update_prices(self, price_data: Dict):
        """Update price data and clear cache."""
        self._price_data = price_data
        self.get_model_price.cache_clear()

# Global instance (can be replaced with dependency injection)
price_manager = PriceManager()

def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """
    Estimate the cost of a request in dollars.
    
    Args:
        model_name: Name of the model
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        
    Returns:
        float: Estimated cost in dollars
    """
    model_price = price_manager.get_model_price(model_name)
    input_cost = (input_tokens / 1_000_000) * model_price.get('input', 0)
    output_cost = (output_tokens / 1_000_000) * model_price.get('output', 0)
    return input_cost + output_cost

def initialize_prices():
    """Initialize price data from external source."""
    from grok3 import get_1m_output_cost, ensure_openrouter_models, openrouter_models_cache
    ensure_openrouter_models()
    price_manager.update_prices(openrouter_models_cache.get('price_dict', {}))
