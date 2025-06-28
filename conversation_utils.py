"""
Conversation utilities for handling message history and summaries.

This module provides functions for managing conversation history, including
summarization to keep context within token limits.
"""
from typing import List, Dict, Any


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
    
    # Calculate total size
    total_chars = sum(len(msg.get("content", "")) for msg in history)
    
    # If under the limit, return as is
    if total_chars <= max_chars:
        return history
    
    # Keep the most recent messages intact
    recent_messages = history[-keep_last_n:] if len(history) > keep_last_n else history
    remaining_chars = sum(len(msg.get("content", "")) for msg in recent_messages)
    
    # If recent messages already exceed the limit, we must truncate more aggressively
    if remaining_chars > max_chars:
        # Just keep the last few messages that fit within max_chars
        for i in range(len(recent_messages) - 1, -1, -1):
            if remaining_chars <= max_chars:
                break
            msg_len = len(recent_messages[i].get("content", ""))
            if i > 0:  # Always keep at least the last message
                remaining_chars -= msg_len
                recent_messages.pop(i)
        return recent_messages
    
    # If we need to summarize older messages
    older_messages = history[:-keep_last_n] if len(history) > keep_last_n else []
    if not older_messages:
        return recent_messages
    
    # Create a summary of older messages
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
        summary_text = summary_text[:summary_max_len - 3] + "..."
    
    # Add the summary as a system message at the beginning
    summary_message = {
        "role": "system",
        "content": f"Previous conversation summary:\n{summary_text}"
    }
    
    # Return the summary + recent messages
    return [summary_message] + recent_messages


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
        raise ValueError("Messages must be a list")
    
    valid_messages = []
    
    for msg in messages:
        if not isinstance(msg, dict):
            continue
            
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if not role or not content:
            continue
            
        # Only allow specific roles
        if role not in ["system", "user", "assistant", "function"]:
            continue
            
        valid_messages.append({
            "role": role,
            "content": content
        })
    
    if not valid_messages:
        # Always ensure at least one valid message
        valid_messages.append({
            "role": "user",
            "content": "Hello"
        })
    
    return valid_messages
