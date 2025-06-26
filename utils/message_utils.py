"""
Message utility functions for MyGrok3.

This module provides utilities for handling message validation, history management,
and other common operations on messages.
"""
from typing import List, Dict, Any, Optional
import tiktoken

import logging_config

# Configure logger
logger = logging_config.configure_logger(__name__)


def get_encoder():
    """
    Get the appropriate tokenizer, using a more cost-effective model.
    
    Returns:
        A tiktoken encoder instance
    """
    try:
        # Using cl100k_base instead of gpt-4 for better cost effectiveness
        return tiktoken.get_encoding("cl100k_base")
    except KeyError:
        logger.warning("Failed to get cl100k_base encoding, falling back to default")
        return tiktoken.encoding_for_model("gpt-3.5-turbo")


def get_token_count(text: str) -> int:
    """
    Count the number of tokens in a text string.
    
    Args:
        text: The text to analyze
        
    Returns:
        Token count as an integer
    """
    encoder = get_encoder()
    return len(encoder.encode(text))


def validate_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Validate and sanitize message format.
    
    Args:
        messages: List of message dictionaries to validate
        
    Returns:
        Sanitized messages list with proper format
        
    Raises:
        ValueError: If message format is invalid
    """
    if not isinstance(messages, list):
        logger.warning("Invalid messages format: not a list")
        raise ValueError("Messages must be a list")
    
    valid_messages = []
    
    for msg in messages:
        if not isinstance(msg, dict):
            logger.warning(f"Skipping non-dict message: {type(msg)}")
            continue
            
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if not role or not content:
            logger.warning("Skipping message with missing role or content")
            continue
            
        # Only allow specific roles
        if role not in ["system", "user", "assistant", "function"]:
            logger.warning(f"Skipping message with invalid role: {role}")
            continue
            
        # Add the validated message
        valid_messages.append({
            "role": role,
            "content": content
        })
    
    if not valid_messages:
        # Always ensure at least one valid message
        logger.warning("No valid messages found, adding default message")
        valid_messages.append({
            "role": "user",
            "content": "Hello"
        })
    
    return valid_messages


def summarize_history(
    history: List[Dict[str, str]], 
    max_chars: int = 4000, 
    keep_last_n: int = 8, 
    summary_max_len: int = 1000
) -> List[Dict[str, str]]:
    """
    Summarize conversation history when it exceeds token limits.
    
    This function handles reducing the conversation history size by either:
    1. Truncating to recent messages if size is manageable
    2. Summarizing older context when the history is too large
    
    Args:
        history: List of conversation message dictionaries
        max_chars: Maximum characters to allow before summarizing
        keep_last_n: Number of recent messages to preserve exactly 
        summary_max_len: Maximum length for the summary
        
    Returns:
        A processed list of messages with either:
        - All original messages if under limits
        - Recent messages + a summary message if over limits
    """
    if not history:
        return []
    
    logger.debug(f"Summarizing history: {len(history)} messages, max_chars={max_chars}")
    
    # Calculate total size
    total_chars = sum(len(msg.get("content", "")) for msg in history)
    
    # If under the limit, return as is
    if total_chars <= max_chars:
        logger.debug(f"History within size limits ({total_chars}/{max_chars} chars)")
        return history
    
    # Keep the most recent messages intact
    recent_messages = history[-keep_last_n:] if len(history) > keep_last_n else history
    remaining_chars = sum(len(msg.get("content", "")) for msg in recent_messages)
    
    # If recent messages already exceed the limit, we must truncate more aggressively
    if remaining_chars > max_chars:
        # Just keep the last few messages that fit within max_chars
        logger.debug("Recent messages exceed limit, truncating aggressively")
        for i in range(len(recent_messages) - 1, -1, -1):
            if remaining_chars <= max_chars:
                break
            msg_len = len(recent_messages[i].get("content", ""))
            if i > 0:  # Always keep at least the last message
                remaining_chars -= msg_len
                recent_messages.pop(i)
        
        logger.debug(f"After aggressive truncation: {len(recent_messages)} messages, {remaining_chars} chars")
        return recent_messages
    
    # If we need to summarize older messages
    older_messages = history[:-keep_last_n] if len(history) > keep_last_n else []
    if not older_messages:
        logger.debug("No older messages to summarize")
        return recent_messages
    
    # Create a summary of older messages
    logger.debug(f"Summarizing {len(older_messages)} older messages")
    summary_text = ""
    for msg in older_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Add a condensed version to the summary
        if len(content) > 100:
            content = content[:97] + "..."
        summary_text += f"{role}: {content}\n\n"
    
    # Truncate summary if it's too long
    if len(summary_text) > summary_max_len:
        logger.debug(f"Truncating summary from {len(summary_text)} to {summary_max_len} chars")
        summary_text = summary_text[:summary_max_len - 3] + "..."
    
    # Add the summary as a system message at the beginning
    summary_message = {
        "role": "system",
        "content": f"Previous conversation summary:\n{summary_text}"
    }
    
    logger.debug(f"Final history: 1 summary + {len(recent_messages)} recent messages")
    
    # Return the summary + recent messages
    return [summary_message] + recent_messages
