"""
Session store module for MyGrok3, supporting both in-memory and Redis backends.

This module provides a flexible session management solution that can be configured
via environment variables. It includes automatic cleanup of old, inactive sessions.
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional
import threading
import time
from datetime import datetime
import json
import os
from collections import defaultdict

import logging_config
logger = logging_config.configure_logger(__name__)

try:
    import redis
except ImportError:
    redis = None

# --- In-Memory Session Store ---

class InMemorySessionStore:
    """Thread-safe in-memory session data store."""

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._global_stats = self._default_global_stats()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def _default_global_stats(self):
        return {
            "total_tokens": 0,
            "total_cost": 0.0,
            "requests_count": 0,
            "models_usage": defaultdict(int),
            "last_updated": datetime.now().isoformat(),
        }

    def get_session(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = self._create_new_session()
            return self._sessions[session_id]

    def _create_new_session(self) -> Dict[str, Any]:
        return {
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "messages": [], "token_count": 0, "total_cost": 0.0,
            "requests_count": 0, "models_used": {}, "metadata": {}
        }

    def update_session(self, session_id: str, **kwargs) -> None:
        with self._lock:
            session = self.get_session(session_id)
            session.update(kwargs)
            session["last_active"] = datetime.now().isoformat()

    def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        with self._lock:
            session = self.get_session(session_id)
            session["messages"].append(message)
            session["last_active"] = datetime.now().isoformat()

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return self.get_session(session_id).get("messages", [])

    def update_stats(self, session_id: str, tokens_in: int = 0, tokens_out: int = 0, cost: float = 0.0, model: Optional[str] = None) -> None:
        with self._lock:
            session = self.get_session(session_id)
            session["token_count"] += tokens_in + tokens_out
            session["total_cost"] += cost
            session["requests_count"] += 1
            if model:
                session["models_used"][model] = session["models_used"].get(model, 0) + 1
            self.update_session(session_id)

            self._global_stats["total_tokens"] += tokens_in + tokens_out
            self._global_stats["total_cost"] += cost
            self._global_stats["requests_count"] += 1
            if model:
                self._global_stats["models_usage"][model] += 1
            self._global_stats["last_updated"] = datetime.now().isoformat()

    def get_global_stats(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._global_stats)

    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._sessions)

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(3600)  # Check every hour
            try:
                with self._lock:
                    now = datetime.now()
                    to_delete = []
                    for session_id, session in self._sessions.items():
                        created_at = datetime.fromisoformat(session.get("created_at"))
                        msg_count = len(session.get("messages", []))
                        if (now - created_at).total_seconds() > 8 * 3600 and msg_count < 5:
                            to_delete.append(session_id)
                    
                    for session_id in to_delete:
                        del self._sessions[session_id]
                        logger.info(f"Cleaned up short, inactive in-memory session: {session_id}")
            except Exception as e:
                logger.error(f"Error in InMemorySessionStore cleanup thread: {e}")

# --- Redis Session Store ---

class RedisSessionStore(InMemorySessionStore):
    """A session store using Redis, with an in-memory fallback."""

    def __init__(self, host='localhost', port=6379, db=0):
        super().__init__() # Initializes cleanup thread and other basics
        self.redis = None
        if redis is None:
            logger.error("Redis library not installed. `pip install redis`. Falling back to in-memory store.")
            return
        try:
            self.redis = redis.Redis(host=host, port=port, db=db, decode_responses=True)
            self.redis.ping()
            logger.info(f"Successfully connected to Redis at {host}:{port}")
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Could not connect to Redis: {e}. Falling back to in-memory store.")
            self.redis = None

    def get_session(self, session_id: str) -> Dict[str, Any]:
        if not self.redis: return super().get_session(session_id)
        session_key = f"session:{session_id}"
        session_data = self.redis.get(session_key)
        if session_data:
            return json.loads(session_data)
        else:
            new_session = self._create_new_session()
            self.redis.set(session_key, json.dumps(new_session))
            return new_session

    def update_session(self, session_id: str, **kwargs) -> None:
        if not self.redis: return super().update_session(session_id, **kwargs)
        session_key = f"session:{session_id}"
        with self.redis.pipeline() as pipe:
            try:
                pipe.watch(session_key)
                session_data = pipe.get(session_key)
                session = json.loads(session_data) if session_data else self._create_new_session()
                session.update(kwargs)
                session["last_active"] = datetime.now().isoformat()
                pipe.multi()
                pipe.set(session_key, json.dumps(session))
                pipe.execute()
            except redis.exceptions.WatchError:
                logger.warning(f"WatchError on session {session_id}, retrying update.")
                time.sleep(0.1)
                self.update_session(session_id, **kwargs)

    def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        if not self.redis: return super().add_message(session_id, message)
        session = self.get_session(session_id)
        session["messages"].append(message)
        self.update_session(session_id, messages=session["messages"])

    def delete_session(self, session_id: str) -> bool:
        if not self.redis: return super().delete_session(session_id)
        return self.redis.delete(f"session:{session_id}") > 0

    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        if not self.redis: return super().get_all_sessions()
        session_keys = self.redis.keys('session:*')
        if not session_keys: return {}
        sessions = self.redis.mget(session_keys)
        return {key.split(':')[1]: json.loads(s) for key, s in zip(session_keys, sessions) if s}

    def _cleanup_loop(self) -> None:
        # Override cleanup to work with Redis
        while True:
            time.sleep(3600) # Check every hour
            if not self.redis:
                super()._cleanup_loop() # Fallback to in-memory cleanup
                continue
            try:
                now = datetime.now()
                to_delete = []
                for key in self.redis.scan_iter('session:*'):
                    session_data = self.redis.get(key)
                    if not session_data: continue
                    session = json.loads(session_data)
                    created_at = datetime.fromisoformat(session.get("created_at"))
                    msg_count = len(session.get("messages", []))
                    if (now - created_at).total_seconds() > 8 * 3600 and msg_count < 5:
                        to_delete.append(key)
                
                if to_delete:
                    self.redis.delete(*to_delete)
                    logger.info(f"Cleaned up {len(to_delete)} short, inactive Redis sessions.")
            except Exception as e:
                logger.error(f"Error in RedisSessionStore cleanup thread: {e}")

# --- Singleton Factory ---

_instance = None
_instance_lock = threading.Lock()

def get_session_store():
    """Factory function to get the appropriate session store instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                if os.environ.get('USE_REDIS', 'false').lower() == 'true':
                    logger.info("USE_REDIS is true, attempting to use RedisSessionStore.")
                    redis_host = os.environ.get('REDIS_HOST', 'localhost')
                    redis_port = int(os.environ.get('REDIS_PORT', 6379))
                    _instance = RedisSessionStore(host=redis_host, port=redis_port)
                else:
                    logger.info("Using InMemorySessionStore.")
                    _instance = InMemorySessionStore()
    return _instance

# Alias for backwards compatibility
store = get_session_store()
