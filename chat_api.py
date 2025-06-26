"""
Chat API blueprint for MyGrok3.

This module implements chat-related API endpoints as a Flask Blueprint.
"""
from flask import Blueprint, request, Response, stream_with_context, jsonify, g
from typing import Dict, List, Any, Generator

from session_store import get_session_store
from chat_handler import generate_chat_response, FinalStats, generate_title
from conversation_utils import summarize_history
from cost_calculator import estimate_cost, CostTracker
from response_utils import get_token_count
import logging_config

# Configure logger
logger = logging_config.configure_logger(__name__)

# Debug flag
DEBUG_MESSAGES = False

# Create chat blueprint
chat_bp = Blueprint('chat', __name__)

# Flag to switch between experimental and stable model lists - moved here from grok3.py
USE_STABLE_MODELS = False

# Model configurations - moved here from grok3.py/routes.py
from models_config import MODELS_EXPERIMENTAL, MODELS_STABLE

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

            # Create a cost_tracker to generate the final footer
            session_data = store.get_session(session_id)
            cost_tracker = CostTracker()
            # This tracker holds the cost/tokens for the CURRENT response
            cost_tracker.update(final_stats_obj.input_tokens, final_stats_obj.output_tokens, final_stats_obj.estimated_cost)
            # These attributes hold the CUMULATIVE data for the whole session
            cost_tracker.session_cumulative_token = session_data.get('token_count', 0)
            cost_tracker.session_cumulative_cost = session_data.get('total_cost', 0.0)

            diagnostics = cost_tracker.get_diagnostic_info(
                model_name=final_stats_obj.model_name,
                output_text=final_stats_obj.full_answer,
                is_debug=True
            )
            if diagnostics:
                yield f"\n\n---\n{diagnostics}"
    
    return Response(
        stream_with_context(streaming_with_stats()),
        mimetype='text/plain'
    )


@chat_bp.route('/api/title_summary', methods=['POST'])
def api_title_summary():
    """
    Generate a title for the conversation.
    
    Returns:
        JSON with title
    """
    data = request.json
    history = data.get('messages', [])
    
    if len(history) < 2: # Don't generate title for very short conversations
        return jsonify({"title": "新会话", "summary": ""})
    
    # Get session ID from Flask g object
    session_id = getattr(g, 'session_id', 'default')
    
    # Generate title using the new handler function
    generated_title = generate_title(history)
    
    # Update the session metadata with title
    store = get_session_store()
    session_data = store.get_session(session_id)
    metadata = session_data.get('metadata', {})
    metadata['title'] = generated_title
    store.update_session(session_id, metadata=metadata)
    
    logger.info(f"Updated title for session {session_id} to '{generated_title}'")
    
    return jsonify({
        "title": generated_title,
        "summary": "" # Summary is not implemented
    })


@chat_bp.route('/api/models', methods=['GET'])
def api_models():
    """
    Get the list of available models.
    
    Returns:
        JSON with the model list
    """
    return jsonify({"models": MODELS, "default_model": DEFAULT_MODEL})


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
