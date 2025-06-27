"""
Session management module for handling user session data with thread safety.
"""
import time
import threading
import redis
import json
from config import SESSION_EXPIRATION_SECONDS
from collections import defaultdict
from cost_calculator import CostTracker

class SessionManager:
    """Thread-safe session storage with automatic cleanup."""
    
    def __init__(self):
        self.redis_client = redis.Redis(host='redis', port=6379, db=0)  # Use 'redis' service name from docker-compose
        self._lock = threading.Lock()
    
    def get_session(self, session_id):
        """Get or create session data for given session_id."""
        with self._lock:
            session_data_json = self.redis_client.get(f"session:{session_id}")
            if session_data_json is None:
                session_data = {'messages': [], 'cost_tracker': CostTracker().to_dict(), 'last_accessed': time.time()}  # Initialize with default
                self.redis_client.setex(f"session:{session_id}", SESSION_EXPIRATION_SECONDS, json.dumps(session_data))  # Set 24-hour expiration
            else:
                session_data = json.loads(session_data_json)
                session_data['cost_tracker'] = CostTracker.from_dict(session_data['cost_tracker'])
                session_data['last_accessed'] = time.time()
                self.redis_client.setex(f"session:{session_id}", SESSION_EXPIRATION_SECONDS, json.dumps(session_data))  # Update timestamp
            return session_data

# Singleton instance
session_manager = SessionManager()
