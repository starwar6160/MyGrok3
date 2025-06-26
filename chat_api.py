"""
Chat API blueprint for MyGrok3.

This module implements chat-related API endpoints as a Flask Blueprint.
"""
from flask import Blueprint, request, Response, stream_with_context, jsonify, g
from typing import Dict, List, Any, Generator

from MyGrok3.session_store import get_session_store
from MyGrok3.chat_handler import generate_chat_response, FinalStats
from MyGrok3.conversation_utils import summarize_history
from MyGrok3.cost_calculator import estimate_cost
from MyGrok3.response_utils import get_token_count
from MyGrok3 import logging_config

# Configure logger
logger = logging_config.configure_logger(__name__)

# Debug flag
DEBUG_MESSAGES = False

# Create chat blueprint
chat_bp = Blueprint('chat', __name__)

# Flag to switch between experimental and stable model lists - moved here from grok3.py
USE_STABLE_MODELS = False

# Model configurations - moved here from grok3.py/routes.py
MODELS_EXPERIMENTAL = [        
    # Gemini models
    "google/gemini-flash-1.5-8b",    #3.8/15            
    "google/gemini-2.5-flash-lite-preview-06-17",   #10/40   
    "google/gemma-3-12b-it",    #5/10
    "google/gemma-3-27b-it:free",    #10/19         
    
    # Other models
    "qwen/qwen3-32b:free",    #10/30
    "moonshotai/kimi-dev-72b:free",       
    
    # General economic models
    "openai/gpt-4o-mini",  #15/60
    "x-ai/grok-3-mini",  #30/50    
    "deepseek/deepseek-r1-distill-llama-70b:free",   #10/40
    "deepseek/deepseek-r1-0528:free",    #55/219    
]

MODELS_STABLE = [
    "google/gemini-2.5-flash-lite-preview-06-17",  #10/40    
    "x-ai/grok-3-mini",    
    "openai/gpt-4o-mini",
    "deepseek/deepseek-r1-distill-llama-70b:free",
]

MODELS = MODELS_STABLE if USE_STABLE_MODELS else MODELS_EXPERIMENTAL
DEFAULT_MODEL = MODELS[0]


@chat_bp.route('/api/chat', methods=['POST'])
def api_chat():
    """
    Handle chat requests from the frontend.
    
    Returns:
        Streaming response with chat content
    """
    data = request.json
    question = data.get('question', '')
    history = data.get('history', [])
    selected_model = data.get('model', DEFAULT_MODEL)
    
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
        
    # Get session ID from Flask g object
    session_id = getattr(g, 'session_id', 'default')
    
    # Get the session store
    store = get_session_store()
    
    # Append the user's question to history
    history.append({"role": "user", "content": question})
    
    # Save the updated history to session store
    store.update_session(session_id, messages=history)
    
    # Summarize history to manage context length
    messages = summarize_history(history, max_chars=2000)
    
    if DEBUG_MESSAGES:
        logger.debug(f"[api_chat] question_length={len(question)}")
        logger.debug(f"[api_chat] model={selected_model}")
        logger.debug(f"[api_chat] history_count={len(history)}")
    
    # Create streaming response
    def streaming_with_stats() -> Generator[str, None, None]:
        """Generate streaming response and track stats."""
        final_stats_obj = None

        # Stream the response and get final stats
        for item in generate_chat_response(selected_model, messages):
            if isinstance(item, str):
                yield item
            elif isinstance(item, FinalStats):
                final_stats_obj = item

        # After streaming, update session with final stats
        if final_stats_obj:
            store.update_stats(
                session_id=session_id, 
                model=final_stats_obj.model_name,
                tokens_in=final_stats_obj.input_tokens,
                tokens_out=final_stats_obj.output_tokens,
                cost=final_stats_obj.estimated_cost
            )
            
            # Add assistant response to history
            store.add_message(session_id, {
                "role": "assistant",
                "content": final_stats_obj.full_answer
            })
            
            logger.debug(
                f"Chat completed for session {session_id}. "
                f"Model: {final_stats_obj.model_name}, "
                f"Tokens: {final_stats_obj.input_tokens + final_stats_obj.output_tokens}, "
                f"Cost: ${final_stats_obj.estimated_cost:.6f}"
            )
    
    return Response(
        stream_with_context(streaming_with_stats()),
        mimetype='text/plain'
    )


@chat_bp.route('/api/title_summary', methods=['POST'])
def api_title_summary():
    """
    Generate a title and summary for the conversation.
    
    Returns:
        JSON with title and summary
    """
    data = request.json
    history = data.get('messages', [])
    
    if not history:
        return jsonify({"title": "", "summary": ""})
    
    # Get session ID from Flask g object
    session_id = getattr(g, 'session_id', 'default')
    
    # Generate title and summary using a model
    # For now, returning placeholders (would use LLM model in real implementation)
    sample_title = "Generated Title"
    sample_summary = "Generated Summary"
    
    # Update the session metadata with title and summary
    store = get_session_store()
    metadata = store.get_session(session_id).get('metadata', {})
    metadata.update({
        "title": sample_title,
        "summary": sample_summary
    })
    store.update_session(session_id, metadata=metadata)
    
    return jsonify({
        "title": sample_title,
        "summary": sample_summary
    })


@chat_bp.route('/api/session_stats', methods=['GET'])
def api_session_stats():
    """
    Get statistics for the current session and global usage.
    
    Returns:
        JSON with session and global statistics
    """
    # Get session ID from Flask g object
    session_id = getattr(g, 'session_id', 'default')
    
    store = get_session_store()
    session_data = store.get_session(session_id)
    global_stats = store.get_global_stats()
    
    return jsonify({
        "session_stats": {
            "token_count": session_data.get("token_count", 0),
            "total_cost": session_data.get("total_cost", 0.0),
            "requests_count": session_data.get("requests_count", 0),
            "models_used": session_data.get("models_used", {})
        },
        "global_stats": {
            "total_tokens": global_stats.get("total_tokens", 0),
            "total_cost": global_stats.get("total_cost", 0.0),
            "requests_count": global_stats.get("requests_count", 0),
            "models_usage": dict(global_stats.get("models_usage", {}))
        }
    })


def register_blueprint(app):
    """
    Register the chat blueprint with the Flask application.
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(chat_bp)
    logger.info("Chat API blueprint registered")
