"""
Utility functions for handling response diagnostics including token counting and cost calculation.
"""
from flask import g
import tiktoken
import json
import time
import threading
from collections import defaultdict
from functools import wraps

# Global in-memory storage with thread lock
session_data_lock = threading.Lock()
session_store = defaultdict(dict)  # Format: {session_id: {'messages': [], 'cost_tracker': CostTracker, 'last_accessed': timestamp}}

class CostTracker:
    """Track token usage and costs across requests."""
    
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cumulative_cost = 0.0
    
    def update(self, input_tokens=0, output_tokens=0, cost=0.0):
        """Update token counts and cost with validation."""
        if cost < 0:
            print(f"[WARNING] Negative cost detected: {cost}, ignoring")
            return
            
        # Atomic update with validation
        new_cumulative = self.cumulative_cost + cost
        if new_cumulative < self.cumulative_cost:
            print(f"[ERROR] Cost would decrease from {self.cumulative_cost} to {new_cumulative}")
            return
            
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cumulative_cost = new_cumulative
        print(f"[COST_UPDATE] Added {cost:.6f}, New Cumulative: {self.cumulative_cost:.6f}")

    def get_diagnostic_info(self, model_name, input_text='', output_text='', is_debug=True):
        """Generate diagnostic string with model info and costs."""
        try:
            # Format cumulative cost
            if self.cumulative_cost >= 0.01:
                cost_str = f"{self.cumulative_cost:.2f}"
            else:
                cost_str = f"{self.cumulative_cost:.1e}"

            diagnostics = f"Model:{model_name}|CurrentTokens:{self.input_tokens + self.output_tokens}|累计费用:{cost_str}美分"
            print(f"[DIAGNOSTIC INFO] {diagnostics}")
            return diagnostics
        except Exception as e:
            print(f"[ERROR] Failed to generate diagnostics: {e}")
            return ""

def get_session_data():
    """Get or create session data for current request."""
    if not hasattr(g, 'session_id'):
        return None
        
    with session_data_lock:
        session_id = g.session_id
        if session_id not in session_store:
            session_store[session_id] = {
                'messages': [],
                'cost_tracker': CostTracker(),
                'last_accessed': time.time()
            }
        else:
            session_store[session_id]['last_accessed'] = time.time()
        return session_store[session_id]

def cleanup_old_sessions(max_age_seconds=86400):
    """Clean up old session data to prevent memory leaks."""
    current_time = time.time()
    with session_data_lock:
        for session_id in list(session_store.keys()):
            if current_time - session_store[session_id].get('last_accessed', 0) > max_age_seconds:
                del session_store[session_id]

# Initialize cleanup thread
cleanup_thread = threading.Thread(
    target=lambda: [time.sleep(3600), cleanup_old_sessions()],
    daemon=True
)
cleanup_thread.start()

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
                session_data = get_session_data()
                if session_data:
                    cost_tracker = session_data['cost_tracker']
                    
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
