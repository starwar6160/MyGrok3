"""
Utility functions for handling response diagnostics including token counting and cost calculation.
"""
from flask import g
import tiktoken
import json
import time
from functools import wraps

# Global session storage for tracking costs across requests
session_costs = {}

def get_token_count(text, model="gpt-3.5-turbo"):
    """Get the number of tokens in a text string."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))

def estimate_cost(model_name, input_tokens, output_tokens):
    """
    Estimate the cost of a request in dollars.
    
    Args:
        model_name: Name of the model
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        
    Returns:
        float: Estimated cost in dollars
    """
    from grok3 import get_1m_output_cost, ensure_openrouter_models, openrouter_models_cache
    ensure_openrouter_models()
    price_dict = openrouter_models_cache.get('price_dict', {})
    model_price = price_dict.get(model_name, {})
    
    input_cost = (input_tokens / 1_000_000) * model_price.get('input', 0)
    output_cost = (output_tokens / 1_000_000) * model_price.get('output', 0)
    
    return input_cost + output_cost

class CostTracker:
    """Track token usage and costs across requests."""
    
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.start_time = time.time()
        self.cumulative_cost = 0.0
    
    def update(self, input_tokens=0, output_tokens=0, cost=0.0):
        """Update token counts and cost."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cumulative_cost += cost
    
    def get_diagnostic_info(self, model_name, input_text, output_text, is_debug=True):
        """Generate a concise, single-line diagnostic string with costs in cents (0.01 precision)."""
        try:
            input_tokens = get_token_count(input_text)
            output_tokens = get_token_count(output_text)
            total_tokens = input_tokens + output_tokens

            model_price = {}
            try:
                from grok3 import openrouter_models_cache
                price_dict = openrouter_models_cache.get('price_dict', {})
                model_price = price_dict.get(model_name, {})
                if not model_price and '/' in model_name:
                    base_model = model_name.split('/')[-1]
                    model_price = price_dict.get(base_model, {})
            except ImportError:
                pass  # openrouter_models_cache not available

            if not model_price:
                KNOWN_MODEL_PRICES = {
                    'google/gemini-flash-1.5-8b': {'input': 0.10, 'output': 0.40},
                    'gpt-3.5-turbo': {'input': 0.50, 'output': 1.50},
                }
                model_price = KNOWN_MODEL_PRICES.get(model_name, {'input': 0, 'output': 0})

            def price_to_cents_per_million(val):
                try:
                    return float(val) * 1_000_000 * 100
                except (ValueError, TypeError):
                    return 0.0

            input_price_cents = price_to_cents_per_million(model_price.get('input', 0))
            output_price_cents = price_to_cents_per_million(model_price.get('output', 0))

            total_cost_cents = ((input_tokens / 1_000_000) * input_price_cents) + \
                               ((output_tokens / 1_000_000) * output_price_cents)
            
            self.cumulative_cost += total_cost_cents

            if not is_debug and self.cumulative_cost < 0.1:
                return ""

            cost_info = f"|Cost:{total_cost_cents:.4f}¢" if total_cost_cents > 0.1 else ""
            diagnostics = f"Model:{model_name}|Tokens:{total_tokens}{cost_info}"
            diagnostics = diagnostics.replace(" ", "")

            if output_price_cents > 100:
                diagnostics += "|⚠️HighOutputPrice"
            if input_price_cents > 100:
                diagnostics += "|⚠️HighInputPrice"

            print(f"[DIAGNOSTIC INFO] {diagnostics}")
            return diagnostics

        except Exception as e:
            error_msg = f"Error generating diagnostics: {e}"
            print(f"[ERROR] In get_diagnostic_info: {error_msg}")
            return error_msg
            
        return diagnostics

def get_cost_tracker():
    """Get or create a cost tracker for the current session."""
    if 'cost_tracker' not in g:
        g.cost_tracker = CostTracker()
    return g.cost_tracker

def with_diagnostics(model_name_key='model', is_debug=False):
    """Decorator to add diagnostic information to responses."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Call the original function
            response = f(*args, **kwargs)
            
            # Only process successful responses
            if not response or not hasattr(response, 'get_json'):
                return response
                
            try:
                data = response.get_json()
                if not isinstance(data, dict):
                    return response
                    
                # Get input and output text
                input_text = data.get('input', '')
                output_text = data.get('output', '')
                model_name = data.get(model_name_key, 'unknown')
                
                # Get or create cost tracker
                cost_tracker = get_cost_tracker()
                
                # Add diagnostic info
                diagnostics = cost_tracker.get_diagnostic_info(
                    model_name=model_name,
                    input_text=input_text,
                    output_text=output_text,
                    is_debug=is_debug
                )
                
                if diagnostics:
                    if isinstance(output_text, str):
                        data['output'] = output_text + diagnostics
                    elif isinstance(data.get('choices'), list) and data['choices']:
                        if 'text' in data['choices'][0]:
                            data['choices'][0]['text'] += diagnostics
                        elif 'message' in data['choices'][0] and 'content' in data['choices'][0]['message']:
                            data['choices'][0]['message']['content'] += diagnostics
                
                # Update the response
                response.set_data(json.dumps(data))
                
            except Exception as e:
                print(f"Error adding diagnostics: {str(e)}")
                
            return response
        return decorated_function
    return decorator
