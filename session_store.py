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
import sqlite3
from collections import defaultdict

import logging_config
from config import CLEANUP_MAX_AGE_HOURS, CLEANUP_MIN_MESSAGES
logger = logging_config.configure_logger(__name__)

try:
    import redis
except ImportError:
    redis = None

# --- In-Memory Session Store ---

class InMemorySessionStore:
    DB_FILE = "sessions.db"
    """Session data store that interacts directly with an SQLite database."""

    def __init__(self):
        self._lock = threading.RLock()
        self._init_db()
        # The cleanup thread remains to clean the database periodically.
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
            with sqlite3.connect(self.DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT session_data FROM sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
                else:
                    new_session = self._create_new_session()
                    self.update_session(session_id, **new_session) # Persist it immediately
                    return new_session

    def _create_new_session(self) -> Dict[str, Any]:
        return {
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "messages": [], "token_count": 0, "total_cost": 0.0,
            "requests_count": 0, "models_used": {}, "metadata": {}
        }

    def update_session(self, session_id: str, **kwargs) -> None:
        with self._lock:
            # Retrieve the current session data to update it
            # This is a simplified approach. For high-concurrency, a more robust read-modify-write is needed.
            with sqlite3.connect(self.DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT session_data FROM sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                session = json.loads(row[0]) if row else self._create_new_session()

                session.update(kwargs)
                session["last_active"] = datetime.now().isoformat()

                cursor.execute('''
                    INSERT INTO sessions (session_id, session_data, last_updated)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        session_data = excluded.session_data,
                        last_updated = excluded.last_updated;
                ''', (session_id, json.dumps(session), datetime.now()))
                conn.commit()

    def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        with self._lock:
            session = self.get_session(session_id)
            session["messages"].append(message)
            self.update_session(session_id, messages=session["messages"])

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        return self.get_session(session_id).get("messages", [])

    def update_stats(self, session_id: str, tokens_in: int = 0, tokens_out: int = 0, cost: float = 0.0, model: Optional[str] = None) -> None:
        with self._lock:
            session = self.get_session(session_id)
            session["token_count"] = session.get("token_count", 0) + tokens_in + tokens_out
            session["total_cost"] = session.get("total_cost", 0.0) + cost
            session["requests_count"] = session.get("requests_count", 0) + 1
            if model:
                if "models_used" not in session:
                    session["models_used"] = {}
                session["models_used"][model] = session["models_used"].get(model, 0) + 1
            self.update_session(session_id, **session)

            # Global stats would need a separate persistence mechanism if required.
            # For now, we remove the direct update to simplify.
            pass

    def get_global_stats(self) -> Dict[str, Any]:
        # This should be re-implemented to pull from a persistent store if needed.
        logger.warning("get_global_stats is returning a default, non-persistent value.")
        return self._default_global_stats()

    def _init_db(self):
        with sqlite3.connect(self.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    session_data TEXT NOT NULL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()






    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            with sqlite3.connect(self.DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT session_id, session_data FROM sessions")
                rows = cursor.fetchall()
                sessions = {}
                for row in rows:
                    try:
                        sessions[row[0]] = json.loads(row[1])
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode session data for {row[0]} from DB")
                return sessions

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            with sqlite3.connect(self.DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                conn.commit()
                return cursor.rowcount > 0

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(3600)  # Clean up every hour
            try:
                with self._lock:
                    with sqlite3.connect(self.DB_FILE) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT session_id, session_data FROM sessions")
                        rows = cursor.fetchall()
                        now = datetime.now()
                        to_delete = []
                        for session_id, session_data_json in rows:
                            try:
                                session = json.loads(session_data_json)
                                created_at = datetime.fromisoformat(session.get("created_at"))
                                ai_replies = len([m for m in session.get("messages", []) if m.get("role") == "assistant"])
                                
                                if (now - created_at).total_seconds() > CLEANUP_MAX_AGE_HOURS * 3600 and ai_replies < CLEANUP_MIN_MESSAGES:
                                    to_delete.append(session_id)
                            except (json.JSONDecodeError, TypeError):
                                logger.error(f"Could not parse session {session_id} for cleanup.")

                        if to_delete:
                            cursor.executemany("DELETE FROM sessions WHERE session_id = ?", [(sid,) for sid in to_delete])
                            conn.commit()
                            logger.info(f"Cleaned up {len(to_delete)} short, inactive sessions from SQLite.")
            except sqlite3.Error as e:
                logger.error(f"Error in SQLite cleanup loop: {e}")
            except Exception as e:
                logger.error(f"An unexpected error occurred in the cleanup loop: {e}")

# --- Singleton Factory ---

_instance = None
_instance_lock = threading.Lock()

def get_session_store():
    """Factory function to get the session store instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                logger.info("Initializing InMemorySessionStore with SQLite backend.")
                _instance = InMemorySessionStore()
    return _instance

# Alias for backwards compatibility
store = get_session_store()
