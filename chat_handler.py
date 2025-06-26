"""
Chat handler module for MyGrok3.

This module centralizes all chat-related functionality, including streaming and
non-streaming responses from LLM models.
"""
import openai
import os
from typing import Dict, List, Any, Generator, Optional, Union
import time
from dataclasses import dataclass

from MyGrok3.cache_manager import get_from_cache, add_to_cache
from MyGrok3.conversation_utils import validate_messages
from MyGrok3.cost_calculator import CostTracker, estimate_cost
from MyGrok3.response_utils import get_token_count
from MyGrok3 import logging_config

logger = logging_config.configure_logger(__name__)

@dataclass
class FinalStats:
    """Data class to hold final token and cost statistics."""
    model_name: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    full_answer: str

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
) -> Generator[Union[str, FinalStats], None, None]:
    """
    Send messages to LLM with streaming response and return final usage data.

    Args:
        model: The model identifier to use
        messages: List of message dictionaries

    Yields:
        - Content chunks from the streaming response (str)
        - The final CompletionUsage object with token counts
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
        
        completion_usage = None
        for chunk in response:
            if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield content
            # The 'usage' field is only present in the final chunk
            if chunk.usage:
                completion_usage = chunk.usage

        # After the loop, yield the final usage object
        if completion_usage:
            logger.info(f"[ask_grok] token usage: {completion_usage}")
            yield completion_usage
                
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
) -> Generator[Union[str, FinalStats], None, None]:
    """
    Generate a chat response, yielding content chunks and final stats.

    Args:
        model: The model identifier to use.
        messages: List of message dictionaries.

    Yields:
        - Content chunks (str).
        - A single FinalStats object at the end of the stream.
    """
    full_answer = ''
    cost_tracker = CostTracker()
    usage_data = None

    try:
        # Process streaming response and get usage data
        for chunk in ask_llm_stream(model, messages):
            if isinstance(chunk, str):
                full_answer += chunk
                yield chunk
            else: # It's the final usage object
                usage_data = chunk

        if usage_data:
            logger.debug(f"[CHAT_HANDLER] Received usage data: {usage_data}")
            input_tokens = usage_data.prompt_tokens
            output_tokens = usage_data.completion_tokens
            logger.debug(f"[CHAT_HANDLER] Updating cost_tracker with: input={input_tokens}, output={output_tokens}")
            estimated_cost = estimate_cost(model, input_tokens, output_tokens)
            cost_tracker.update(input_tokens, output_tokens, estimated_cost)



        else:
            # Fallback for safety, though it shouldn't be reached
            logger.warning("[CHAT_HANDLER] No usage data received. Falling back to manual count.")
            input_tokens = get_token_count(" ".join(m['content'] for m in messages if m.get('content')))
            output_tokens = get_token_count(full_answer)
            logger.debug(f"[CHAT_HANDLER] Fallback cost_tracker update: input={input_tokens}, output={output_tokens}")
            estimated_cost = estimate_cost(model, input_tokens, output_tokens)
            cost_tracker.update(input_tokens, output_tokens, estimated_cost)

        # Yield the final statistics object instead of the footer
        yield FinalStats(
            model_name=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            full_answer=full_answer
        )
    
    except Exception as e:
        error_msg = f"Error in generate_chat_response: {str(e)}"
        logger.error(error_msg)
        import traceback
        traceback.print_exc()
        yield error_msg
