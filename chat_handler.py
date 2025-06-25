"""
Chat handler module for MyGrok3.

This module centralizes all chat-related functionality, including streaming and
non-streaming responses from LLM models.
"""
import openai
import os
from typing import Dict, List, Any, Generator, Optional
import time

from MyGrok3.cache_manager import get_from_cache, add_to_cache
from MyGrok3.conversation_utils import validate_messages
from MyGrok3.cost_calculator import CostTracker, estimate_cost
from MyGrok3.response_utils import get_token_count, with_diagnostics
from MyGrok3 import logging_config

logger = logging_config.configure_logger(__name__)

# Configure the OpenRouter API client
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=openai_api_key
)

# Debug flag
DEBUG_MESSAGES = os.environ.get('DEBUG_MESSAGES') == 'true'


def ask_llm_stream(
    model: str, 
    messages: List[Dict[str, str]]
) -> Generator[str, None, None]:
    """
    Send messages to LLM with streaming response.
    
    Args:
        model: The model identifier to use
        messages: List of message dictionaries
        
    Yields:
        Content chunks from the streaming response
    """
    validated_messages = validate_messages(messages)
    
    if DEBUG_MESSAGES:
        logger.debug(f"Streaming request to model {model}")
        logger.debug(f"Message count: {len(validated_messages)}")
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=validated_messages,
            stream=True
        )
        
        for chunk in response:
            if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield content
                
    except Exception as e:
        error_msg = f"Error in streaming response: {str(e)}"
        logger.error(error_msg)
        yield error_msg


def ask_llm(
    model: str, 
    messages: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Send messages to LLM for a complete (non-streaming) response.
    
    Args:
        model: The model identifier to use
        messages: List of message dictionaries
        
    Returns:
        Complete response from the LLM
    """
    validated_messages = validate_messages(messages)
    
    # Check cache first
    cached_response = get_from_cache(model, validated_messages)
    if cached_response:
        return cached_response
    
    if DEBUG_MESSAGES:
        logger.debug(f"Non-streaming request to model {model}")
        logger.debug(f"Message count: {len(validated_messages)}")
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=validated_messages,
            stream=False
        )
        
        # Cache the response
        add_to_cache(model, validated_messages, response)
        return response
        
    except Exception as e:
        error_msg = f"Error in non-streaming response: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg}


def generate_chat_response(
    model: str, 
    messages: List[Dict[str, str]]
) -> Generator[str, None, None]:
    """
    Generate a complete chat response with diagnostic information.
    
    Args:
        model: The model identifier to use
        messages: List of message dictionaries
        
    Yields:
        Content chunks with final diagnostic information
    """
    full_answer = ''
    input_tokens = 0
    output_tokens = 0
    cost_tracker = CostTracker()
    
    # Calculate input tokens
    try:
        input_tokens = sum(
            get_token_count(msg.get('content', '')) 
            for msg in messages if isinstance(msg, dict)
        )
        
        last_content = None
        
        # Process streaming response
        for chunk in ask_llm_stream(model, messages):
            full_answer += chunk
            if last_content is not None:
                yield last_content
            last_content = chunk
        
        # Yield the last content chunk
        if last_content is not None:
            yield last_content
        
        # Calculate tokens and costs
        output_tokens = get_token_count(full_answer)
        estimated_cost = estimate_cost(model, input_tokens, output_tokens)
        
        # Update cost tracker
        cost_tracker.update(input_tokens, output_tokens, estimated_cost)
        
        # Generate diagnostic info
        diagnostics = cost_tracker.get_diagnostic_info(
            model_name=model,
            input_text='',  # Don't include full text
            output_text=full_answer,
            is_debug=True
        )
        
        if diagnostics:
            # Add separator and diagnostics
            yield f"\n\n---\n{diagnostics}"
            
            if DEBUG_MESSAGES:
                logger.debug(f"[DIAGNOSTICS] {diagnostics}")
    
    except Exception as e:
        error_msg = f"Error in generate_chat_response: {str(e)}"
        logger.error(error_msg)
        import traceback
        traceback.print_exc()
        yield error_msg
