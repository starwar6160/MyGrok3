"""
Module for handling cost calculations and token tracking with improved structure.
"""
from typing import Optional, Dict
import logging_config
import logging
import threading
from functools import lru_cache
import json
import models_config

# Get configured logger
logger = logging_config.configure_logger(__name__)

class CostTracker:
    """Track token usage and costs across requests."""
    
    def __init__(self):
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost = 0.0
        self.session_cumulative_token: Optional[int] = None
        self.session_cumulative_cost: Optional[float] = None
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
    def cost(self) -> float:
        """Get the current cost."""
        return self._cost
    
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
            
        new_cost = self._cost + cost
        if new_cost < self._cost:
            logger.error(f"Cost would decrease from {self._cost} to {new_cost}")
            return
            
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._cost = new_cost
    
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
            
            # Determine which cost to display (cumulative or current)
            display_cost = self.session_cumulative_cost if self.session_cumulative_cost is not None else self._cost

            def format_cost(cost_usd: float) -> str:
                """
                Format cost with appropriate units based on its value.

                - If cost is effectively zero, return "0".
                - If cost is less than 0.01 cents ($0.0001), display in integer picocents (1e-12 units).
                - Otherwise, display in cents with two decimal places.
                """
                if abs(cost_usd) < 1e-15: # Use a smaller threshold for picodollar precision
                    return "0"
                
                cents = cost_usd * 100
                if cents < 0.01:
                    picodollars = cost_usd * 1_000_000_000_000
                    # If picodollars would round to 0, but the cost is non-zero, show 1 to indicate a small cost.
                    if round(picodollars) == 0 and cost_usd > 0:
                        return "1"
                    return f"{int(round(picodollars))}"
                else:
                    return f"{cents:.2f}美分"

            cost_display = format_cost(display_cost)

            # Fallback for cumulative token display
            total_tokens_display = self.session_cumulative_token if self.session_cumulative_token is not None else (self._input_tokens + self._output_tokens)

            base_info = f"Model:{display_model}|CurrentTokens:{self._input_tokens + self._output_tokens}|TotalTokens:{total_tokens_display}|累计费用:{cost_display}"
            
            # Add debug information if requested
            if is_debug:
                debug_info = []
                if input_text is not None:
                    input_sample = input_text[:50] + '...' if len(input_text) > 50 else input_text
                    # 仅当input内容非空时添加
                    if input_sample.strip() != '':
                        debug_info.append(f"Input: '{input_sample}'")
                # 不再添加 Output 部分
                if debug_info:
                    base_info = f"{base_info} | {' | '.join(debug_info)}"
            
            return base_info
            
        except Exception as e:
            logger.error(f"Failed to generate diagnostics: {e}")
            return f"|Error generating diagnostics: {str(e)}|"

    def to_dict(self):
        return {
            'input_tokens': self._input_tokens,
            'output_tokens': self._output_tokens,
            'cost': self._cost,
            'session_cumulative_token': self.session_cumulative_token,
            'session_cumulative_cost': self.session_cumulative_cost,
            'model_name': self._model_name
        }

    @staticmethod
    def from_dict(data):
        ct = CostTracker()
        ct._input_tokens = data['input_tokens']
        ct._output_tokens = data['output_tokens']
        ct._cost = data['cost']
        ct.session_cumulative_token = data['session_cumulative_token']
        ct.session_cumulative_cost = data['session_cumulative_cost']
        ct._model_name = data['model_name']
        return ct


class PriceManager:
    """Manages loading and accessing model price data with lazy initialization."""
    def __init__(self):
        self._price_data: Dict = {}
        self._init_lock = threading.Lock()

    @lru_cache(maxsize=32)
    def get_model_price(self, model_name: str) -> Dict[str, float]:
        """Get pricing info for a model, triggering initialization if needed."""
        if not self._price_data:
            with self._init_lock:
                # Double-check after acquiring lock to prevent re-initialization
                if not self._price_data:
                    logger.info("[PriceManager] Price data empty. Triggering lazy initialization.")
                    from cost_calculator import initialize_prices
                    initialize_prices()
        return self._price_data.get(model_name, {'input': 0, 'output': 0})
    
    def update_prices(self, price_data: Dict):
        """Update price data and clear cache."""
        self._price_data = price_data
        logger.info(f"[PriceManager] Prices updated with {len(price_data)} models. Cache cleared.")
        self.get_model_price.cache_clear()

# Global instance (can be replaced with dependency injection)
price_manager = PriceManager()

def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the cost of a request based on token counts.
    
    Args:
        model_name: Name of the model
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        
    Returns:
        float: Estimated cost in dollars
    """
    logger.debug(f"[ESTIMATE_COST] Requesting price for model: '{model_name}'")
    price_keys = list(price_manager._price_data.keys())
    if not price_keys:
        logger.warning("[ESTIMATE_COST] Price manager is empty.")
    else:
        logger.debug(f"[ESTIMATE_COST] Available price keys: {price_keys[:5]}...")

    model_price = price_manager.get_model_price(model_name)
    logger.debug(f"[ESTIMATE_COST] Price for model '{model_name}': {model_price}")
    if model_price.get('input', 0) == 0 and model_price.get('output', 0) == 0:
        logger.warning(f"[ESTIMATE_COST] Price for model '{model_name}' is zero.")

    input_cost = (input_tokens / 1_000_000) * model_price.get('input', 0)
    output_cost = (output_tokens / 1_000_000) * model_price.get('output', 0)
    return input_cost + output_cost

def initialize_prices(force_refresh: bool = False):
    """Initialize or refresh price data, with fallback mechanisms.

    Args:
        force_refresh: If True, forces a fetch from the remote API,
                       bypassing any caches.
    """
    from openrouter_manager import ensure_openrouter_models, openrouter_models_cache, _load_price_cache

    try:
        # Step 1: Attempt to get prices (respecting cache unless forced)
        ensure_openrouter_models(force_refresh=force_refresh)
        price_dict = openrouter_models_cache.get('price_dict', {})

        # Step 2: If still no prices, try loading from the on-disk cache as a fallback
        if not price_dict and not force_refresh:
            logger.info("[PRICE INIT] price_dict empty, trying to load from local cache file.")
            _load_price_cache()
            price_dict = openrouter_models_cache.get('price_dict', {})

        # Step 3: If all else fails, use a hardcoded default price list
        if not price_dict:
            logger.error("[PRICE INIT] Price dictionary is still empty. Injecting default price list.")
            price_dict = {
                "google/gemini-flash-1.5-8b": {"input": 0.0004, "output": 0.0004},
                "google/gemini-flash-1.5-8b:free": {"input": 0.0004, "output": 0.0004},
                "google/gemini-flash-1.5-b:latest": {"input": 0.0004, "output": 0.0004},
                models_config.GEMINI_2_5_FLASH_LITE: {"input": 0.001, "output": 0.001},
                f"{models_config.GEMINI_2_5_FLASH_LITE}:free": {"input": 0.001, "output": 0.001},
            }
        else:
            logger.info("[PRICE INIT] Price dictionary loaded successfully.")

        # Step 4: Update the global price manager
        price_manager.update_prices(price_dict)

    except Exception as e:
        logger.error(f"[PRICE INIT] Exception during price initialization: {e}", exc_info=True)
