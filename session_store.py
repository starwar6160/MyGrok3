"""
Thread-safe session store module for MyGrok3.

This module provides a global in-memory structure for storing and managing session data,
including messages, token counts, and cost information across the application.
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional
import threading
import time
from datetime import datetime
import json
from collections import defaultdict

from MyGrok3 import logging_config

logger = logging_config.configure_logger(__name__)

class SessionStore:
    """
    Thread-safe session data store for managing conversation state across the application.
    
    This class provides methods to store and retrieve session data, including:
    - Messages history
    - Token usage statistics
    - Cost tracking information
    - Session metadata
    
    All methods are thread-safe through the use of a reentrant lock.
    """
    
    def __init__(self):
        """Initialize the session store with empty storage and a thread lock."""
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._global_stats: Dict[str, Any] = {
            "total_tokens": 0,
            "total_cost": 0.0,
            "requests_count": 0,
            "models_usage": defaultdict(int),
            "last_updated": datetime.now().isoformat(),
        }
        
        # Start cleanup thread
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, 
            daemon=True
        )
        self._cleanup_thread.start()
        
    def get_session(self, session_id: str) -> Dict[str, Any]:
        """
        Get a session by ID, creating it if it doesn't exist.
        
        Args:
            session_id: Unique identifier for the session
            
        Returns:
            Session data dictionary
        """
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {
                    "created_at": datetime.now().isoformat(),
                    "last_active": datetime.now().isoformat(),
                    "messages": [],
                    "token_count": 0,
                    "total_cost": 0.0,
                    "requests_count": 0,
                    "models_used": {},
                    "metadata": {}
                }
            return self._sessions[session_id]
    
    def update_session(self, session_id: str, **kwargs) -> None:
        """
        Update a session with new data.
        
        Args:
            session_id: Unique identifier for the session
            **kwargs: Key-value pairs to update in the session
        """
        with self._lock:
            session = self.get_session(session_id)
            session.update(kwargs)
            session["last_active"] = datetime.now().isoformat()
    
    def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """
        Add a message to a session's history.
        
        Args:
            session_id: Unique identifier for the session
            message: Message dictionary to add
        """
        with self._lock:
            session = self.get_session(session_id)
            session["messages"].append(message)
            session["last_active"] = datetime.now().isoformat()
    
    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all messages for a session.
        
        Args:
            session_id: Unique identifier for the session
            
        Returns:
            List of message dictionaries
        """
        with self._lock:
            return self.get_session(session_id).get("messages", [])
    
    def update_stats(
        self, 
        session_id: str, 
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0
    ) -> None:
        """
        Update token and cost statistics for a session.
        
        Args:
            session_id: Unique identifier for the session
            model: Model ID used for the request
            tokens_in: Number of input tokens used
            tokens_out: Number of output tokens used
            cost: Cost of the request in USD
        """
        with self._lock:
            # Update session stats
            session = self.get_session(session_id)
            session["token_count"] = session.get("token_count", 0) + tokens_in + tokens_out
            session["total_cost"] = session.get("total_cost", 0.0) + cost
            session["requests_count"] = session.get("requests_count", 0) + 1
            
            # Update model usage for this session
            models_used = session.get("models_used", {})
            models_used[model] = models_used.get(model, 0) + 1
            session["models_used"] = models_used
            
            # Update global stats
            self._global_stats["total_tokens"] += tokens_in + tokens_out
            self._global_stats["total_cost"] += cost
            self._global_stats["requests_count"] += 1
            self._global_stats["models_usage"][model] += 1
            self._global_stats["last_updated"] = datetime.now().isoformat()
    
    def get_global_stats(self) -> Dict[str, Any]:
        """
        Get global usage statistics.
        
        Returns:
            Dictionary with global usage statistics
        """
        with self._lock:
            return dict(self._global_stats)
    
    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all sessions data.
        
        Returns:
            Dictionary mapping session IDs to session data
        """
        with self._lock:
            return dict(self._sessions)
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session by ID.
        
        Args:
            session_id: Unique identifier for the session
            
        Returns:
            True if session was deleted, False if not found
        """
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False
    
    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Export a session's data to a serializable dictionary.
        
        Args:
            session_id: Unique identifier for the session
            
        Returns:
            Session data as a serializable dictionary, or None if not found
        """
        with self._lock:
            if session_id in self._sessions:
                return dict(self._sessions[session_id])
            return None
    
    def export_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        Export all sessions data to a serializable dictionary.
        
        Returns:
            Dictionary mapping session IDs to serializable session data
        """
        with self._lock:
            return {sid: dict(session) for sid, session in self._sessions.items()}
    
    def _cleanup_loop(self) -> None:
        """
        Background thread function that periodically cleans up expired sessions.
        Sessions are considered expired if they've been inactive for more than
        24 hours.
        """
        while True:
            try:
                # Sleep for a while before checking
                time.sleep(3600)  # Check once per hour
                
                with self._lock:
                    now = datetime.now()
                    expired_sessions = []
                    
                    # Find expired sessions (inactive for > 24h)
                    for session_id, session in self._sessions.items():
                        last_active_str = session.get("last_active")
                        if not last_active_str:
                            continue
                            
                        try:
                            last_active = datetime.fromisoformat(last_active_str)
                            time_diff = (now - last_active).total_seconds()
                            
                            # If inactive for more than 24 hours
                            if time_diff > 86400:  # 24h in seconds
                                expired_sessions.append(session_id)
                        except ValueError:
                            # Invalid datetime format, skip
                            logger.warning(f"Invalid datetime format for session {session_id}")
                    
                    # Delete expired sessions
                    for session_id in expired_sessions:
                        del self._sessions[session_id]
                        
                    if expired_sessions:
                        logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
                        
            except Exception as e:
                logger.error(f"Error in session cleanup thread: {e}")


# Global singleton instance
_instance = None
_instance_lock = threading.Lock()

def get_session_store() -> SessionStore:
    """
    Get or create the global SessionStore instance.
    
    This function ensures only one SessionStore instance is created
    and used throughout the application (Singleton pattern).
    
    Returns:
        The global SessionStore instance
    """
    global _instance
    
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SessionStore()
                logger.info("Session store initialized")
    
    return _instance

# Alias for backwards compatibility and convenience
store = get_session_store()
