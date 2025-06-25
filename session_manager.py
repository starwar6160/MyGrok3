"""
Session management module for handling user session data with thread safety.
"""
import time
import threading
from collections import defaultdict
from MyGrok3.cost_calculator import CostTracker

class SessionManager:
    """Thread-safe session storage with automatic cleanup."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._store = defaultdict(dict)  # Format: {session_id: {'messages': [], 'cost_tracker': CostTracker, 'last_accessed': timestamp}}
        self._start_cleanup_thread()
    
    def get_session(self, session_id):
        """Get or create session data for given session_id."""
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = {
                    'messages': [],
                    'cost_tracker': CostTracker(),
                    'last_accessed': time.time()
                }
            else:
                self._store[session_id]['last_accessed'] = time.time()
            return self._store[session_id]
    
    def cleanup_old_sessions(self, max_age_seconds=86400):
        """Clean up sessions older than max_age_seconds."""
        current_time = time.time()
        with self._lock:
            for session_id in list(self._store.keys()):
                if current_time - self._store[session_id].get('last_accessed', 0) > max_age_seconds:
                    del self._store[session_id]
    
    def _start_cleanup_thread(self):
        """Start background thread for periodic session cleanup."""
        cleanup_thread = threading.Thread(
            target=lambda: [time.sleep(3600), self.cleanup_old_sessions()],
            daemon=True
        )
        cleanup_thread.start()

# Singleton instance
session_manager = SessionManager()
