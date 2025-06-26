"""
Decorators for adding diagnostic information to responses.
"""
from flask import g
from functools import wraps
import json
from typing import Callable, Any
from session_manager import session_manager
import logging

logger = logging.getLogger(__name__)

class ResponseFormatter:
    """Format responses with diagnostic information."""
    
    @staticmethod
    def add_diagnostics(data: dict, diagnostics: str) -> dict:
        """Add diagnostics to the response data."""
        if isinstance(data.get('output'), str):
            data['output'] = data['output'] + diagnostics
        elif isinstance(data.get('choices'), list) and data['choices']:
            if 'text' in data['choices'][0]:
                data['choices'][0]['text'] += diagnostics
            elif 'message' in data['choices'][0] and 'content' in data['choices'][0]['message']:
                data['choices'][0]['message']['content'] += diagnostics
        return data

def track_metrics(model_name_key: str = 'model') -> Callable:
    """Decorator to track request metrics (tokens, costs)."""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs) -> Any:
            response = f(*args, **kwargs)
            
            if not response or not hasattr(response, 'get_json'):
                return response
                
            try:
                data = response.get_json()
                if not isinstance(data, dict):
                    return response
                    
                model_name = data.get(model_name_key, 'unknown')
                session_data = session_manager.get_session(getattr(g, 'session_id', None)) if hasattr(g, 'session_id') else None
                
                if session_data and 'cost_tracker' in session_data:
                    diagnostics = session_data['cost_tracker'].get_diagnostic_info(model_name)
                    if diagnostics:
                        data = ResponseFormatter.add_diagnostics(data, diagnostics)
                        response.set_data(json.dumps(data))
                
            except Exception as e:
                logger.error(f"Error in track_metrics: {e}")
                
            return response
        return decorated_function
    return decorator
