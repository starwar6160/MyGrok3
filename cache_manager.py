"""
LLM cache management module.

This module provides utilities for caching LLM responses to reduce API costs
and improve response times for repeated queries.
"""
import hashlib
import json
import time
from typing import Dict, Any, Optional
from types import SimpleNamespace
import sqlite3
import threading
import logging_config

# --- Configuration ---
LLM_CACHE_MAX_SIZE = 1000  # Maximum cache entries
LLM_CACHE_EXPIRY_SECONDS = 3600  # Cache expiry time (1 hour)
DB_FILE = "llm_cache.db"

logger = logging_config.configure_logger(__name__)

# --- Helper Functions ---

def get_cache_key(model: str, messages: list) -> str:
    """
    Generate a cache key based on model and messages.
    
    Args:
        model: The LLM model identifier
        messages: The message history/context
        
    Returns:
        A SHA-256 hash as a hex string for the cache key
    """
    # Sort keys in messages to ensure consistent JSON string
    try:
        key_src = model + json.dumps(messages, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(key_src.encode('utf-8')).hexdigest()
    except Exception as e:
        logger.error(f"Error generating cache key: {e}")
        # Fallback for un-serializable messages
        key_src = model + str(messages)
        return hashlib.sha256(key_src.encode('utf-8')).hexdigest()


# --- SQLite Cache Manager ---

class SQLiteCacheManager:
    """Manages LLM response caching using an SQLite database for persistence."""

    def __init__(self, db_file: str, max_size: int, expiry_seconds: int):
        self.db_file = db_file
        self.max_size = max_size
        self.expiry_seconds = expiry_seconds
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Initialize the database and create the cache table if it doesn't exist."""
        with self._lock:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS llm_cache (
                        cache_key TEXT PRIMARY KEY,
                        response TEXT NOT NULL,
                        timestamp INTEGER NOT NULL
                    )
                ''')
                conn.commit()

    def get(self, model: str, messages: list) -> Optional[Any]:
        """Retrieve a cached response if it exists and is not expired."""
        cache_key = get_cache_key(model, messages)
        with self._lock:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT response, timestamp FROM llm_cache WHERE cache_key = ?",
                    (cache_key,)
                )
                row = cursor.fetchone()

                if row:
                    response_json, timestamp = row
                    if time.time() - timestamp < self.expiry_seconds:
                        logger.info(f"Cache HIT for key: {cache_key[:10]}...")
                        try:
                            response_dict = json.loads(response_json)
                            
                            # Recursively convert dict to a SimpleNamespace object to allow dot notation access
                            def dict_to_obj(d):
                                if isinstance(d, dict):
                                    return SimpleNamespace(**{k: dict_to_obj(v) for k, v in d.items()})
                                elif isinstance(d, list):
                                    return [dict_to_obj(i) for i in d]
                                else:
                                    return d
                            
                            obj_response = dict_to_obj(response_dict)
                            logger.debug(f"Returning object of type {type(obj_response)} from cache.")
                            return obj_response
                        except json.JSONDecodeError:
                            logger.error(f"Failed to decode cached JSON for key {cache_key}")
                            # Corrupt data, delete it
                            self.delete(cache_key)
                            return None
                    else:
                        # Expired, delete it
                        logger.info(f"Cache EXPIRED for key: {cache_key[:10]}...")
                        self.delete(cache_key)
        
        logger.info(f"Cache MISS for key: {cache_key[:10]}...")
        return None

    def add(self, model: str, messages: list, response: Any):
        """Add a response to the cache."""
        cache_key = get_cache_key(model, messages)
        
        # Convert Pydantic model to dict before serializing to JSON
        response_to_serialize = response
        if hasattr(response, 'model_dump'):
            logger.debug(f"Serializing Pydantic model of type {type(response)} to dict for caching.")
            response_to_serialize = response.model_dump()
        
        response_json = json.dumps(response_to_serialize, ensure_ascii=False)
        current_time = int(time.time())

        with self._lock:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO llm_cache (cache_key, response, timestamp)
                    VALUES (?, ?, ?)
                    """,
                    (cache_key, response_json, current_time)
                )
                conn.commit()
                logger.info(f"Cache ADD for key: {cache_key[:10]}...")
        
        # Clean up after adding to ensure cache size is maintained
        self.clean()

    def delete(self, cache_key: str):
        """Deletes a specific entry from the cache."""
        with self._lock:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM llm_cache WHERE cache_key = ?", (cache_key,))
                conn.commit()

    def clean(self):
        """Clean expired entries and enforce cache size limit."""
        with self._lock:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                
                # 1. Delete expired entries
                expired_time = int(time.time()) - self.expiry_seconds
                cursor.execute("DELETE FROM llm_cache WHERE timestamp < ?", (expired_time,))
                
                # 2. Enforce max size by deleting the oldest entries
                cursor.execute("SELECT COUNT(*) FROM llm_cache")
                count = cursor.fetchone()[0]
                
                if count > self.max_size:
                    num_to_delete = count - self.max_size
                    # Find the oldest `num_to_delete` entries and delete them
                    cursor.execute(
                        """
                        DELETE FROM llm_cache WHERE cache_key IN (
                            SELECT cache_key FROM llm_cache ORDER BY timestamp ASC LIMIT ?
                        )
                        """,
                        (num_to_delete,)
                    )
                    logger.info(f"Cache limit exceeded. Removed {num_to_delete} oldest entries.")

                conn.commit()


# --- Singleton Instance and Public Functions ---

_cache_manager_instance = SQLiteCacheManager(
    db_file=DB_FILE,
    max_size=LLM_CACHE_MAX_SIZE,
    expiry_seconds=LLM_CACHE_EXPIRY_SECONDS
)

def get_from_cache(model: str, messages: list) -> Optional[Any]:
    """
    Retrieve a cached response if it exists and is not expired.
    
    Args:
        model: The LLM model identifier
        messages: The message history/context
        
    Returns:
        The cached response or None if not found or expired
    """
    return _cache_manager_instance.get(model, messages)


def add_to_cache(model: str, messages: list, response: Any) -> None:
    """
    Add a response to the cache.
    
    Args:
        model: The LLM model identifier
        messages: The message history/context
        response: The LLM response to cache
    """
    _cache_manager_instance.add(model, messages, response)
