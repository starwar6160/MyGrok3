"""
Utility functions for handling response diagnostics including token counting and cost calculation.
"""
# Standard library imports
from functools import wraps
from typing import Callable, Optional, Dict, Any
import logging

# Third-party imports
from flask import g

# Local application imports
from session_manager import session_manager
from cost_calculator import estimate_cost
from diagnostics import track_metrics, ResponseFormatter
from token_counter import TokenCounter
import logging_config

# Constants
DEFAULT_MODEL = "gpt-3.5-turbo"
MAX_SESSION_AGE = 24 * 60 * 60  # 24 hours in seconds

# Custom Exceptions
class ResponseUtilsError(Exception):
    """Base exception for response utilities."""
    pass

class InvalidSessionError(ResponseUtilsError):
    """Raised when session operations fail."""
    pass

class CostCalculationError(ResponseUtilsError):
    """Raised when cost calculations fail."""
    pass

# Get configured logger
logger = logging_config.configure_logger(__name__)

def get_session_data() -> Optional[Dict[str, Any]]:
    """
    Get or create session data for current request.
    
    Returns:
        Optional[Dict]: Session data dictionary if available
    
    Raises:
        InvalidSessionError: If session retrieval fails
    """
    try:
        if not hasattr(g, 'session_id'):
            return None
        return session_manager.get_session(g.session_id)
    except Exception as e:
        logger.error(f"Session data retrieval failed: {e}")
        raise InvalidSessionError(f"Could not retrieve session data: {e}")

def get_token_count(text: str, model: str = DEFAULT_MODEL) -> int:
    """
    Get the number of tokens in a text string.
    
    Args:
        text: Input text to count tokens for
        model: Model name for tokenization
        
    Returns:
        int: Number of tokens
    """
    try:
        return TokenCounter.count_tokens(text, model)
    except Exception as e:
        logger.error(f"Token counting failed for model {model}: {e}")
        return 0




def with_diagnostics(model_name_key: str = 'model', is_debug: bool = False) -> Callable:
    """Backward-compatibility wrapper that delegates to the new ``track_metrics`` decorator.

    Args:
        model_name_key: JSON key that contains the model name in the response.
        is_debug: Currently unused. Retained for API compatibility.

    Returns:
        Callable: A decorator that adds diagnostics to Flask JSON responses.
    """
    return track_metrics(model_name_key)


