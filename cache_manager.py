"""
LLM cache management module.

This module provides utilities for caching LLM responses to reduce API costs
and improve response times for repeated queries.
"""
import hashlib
import json
import time
from typing import Dict, Any, Optional

# Configuration
LLM_CACHE_MAX_SIZE = 1000  # Maximum cache entries
LLM_CACHE_EXPIRY_SECONDS = 3600  # Cache expiry time (1 hour)

# Simple in-memory cache
# Structure: {cache_key: {"response": response_obj, "timestamp": creation_time}}
llm_cache: Dict[str, Dict[str, Any]] = {}


def get_cache_key(model: str, messages: list) -> str:
    """
    Generate a cache key based on model and messages.
    
    Args:
        model: The LLM model identifier
        messages: The message history/context
        
    Returns:
        A SHA-256 hash as a hex string for the cache key
    """
    key_src = model + json.dumps(messages, ensure_ascii=False)
    return hashlib.sha256(key_src.encode('utf-8')).hexdigest()


def get_from_cache(model: str, messages: list) -> Optional[Dict[str, Any]]:
    """
    Retrieve a cached response if it exists and is not expired.
    
    Args:
        model: The LLM model identifier
        messages: The message history/context
        
    Returns:
        The cached response or None if not found or expired
    """
    clean_expired_cache()
    cache_key = get_cache_key(model, messages)
    
    if cache_key in llm_cache:
        return llm_cache[cache_key]["response"]
    return None


def add_to_cache(model: str, messages: list, response: Any) -> None:
    """
    Add a response to the cache.
    
    Args:
        model: The LLM model identifier
        messages: The message history/context
        response: The LLM response to cache
    """
    clean_expired_cache()
    cache_key = get_cache_key(model, messages)
    
    # Add to cache with timestamp
    llm_cache[cache_key] = {
        "response": response,
        "timestamp": time.time()
    }


def clean_expired_cache() -> None:
    """
    Clean expired entries from the cache and limit cache size.
    """
    global llm_cache
    current_time = time.time()
    
    # Delete expired cache entries
    expired_keys = [
        key for key, value in llm_cache.items() 
        if current_time - value.get("timestamp", 0) > LLM_CACHE_EXPIRY_SECONDS
    ]
    
    for key in expired_keys:
        del llm_cache[key]
    
    # Limit cache size by removing oldest entries if needed
    if len(llm_cache) > LLM_CACHE_MAX_SIZE:
        # Sort by timestamp (oldest first)
        sorted_keys = sorted(
            llm_cache.keys(), 
            key=lambda k: llm_cache[k].get("timestamp", 0)
        )
        
        # Remove oldest entries to bring size within limit
        keys_to_remove = sorted_keys[:len(llm_cache) - LLM_CACHE_MAX_SIZE]
        for key in keys_to_remove:
            del llm_cache[key]
