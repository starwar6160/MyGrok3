"""
Flask routes for MyGrok3.

This module organizes all the Flask routes using blueprints for better
organization and maintainability.
"""
import os
import uuid
from pathlib import Path
from flask import Blueprint, render_template, request, Response, stream_with_context
from flask import g, session, send_from_directory, jsonify

from chat_handler import generate_chat_response
from conversation_utils import summarize_history
from openrouter_manager import (
    ensure_openrouter_models, 
    get_1m_output_cost,
    suggest_cheaper_models,
    openrouter_models_cache
)

# Debug flag
DEBUG_MESSAGES = os.environ.get('DEBUG_MESSAGES') == 'true'

# Flag to switch between experimental and stable model lists
USE_STABLE_MODELS = os.environ.get('USE_STABLE_MODELS') == 'true'

# Model configurations
from models_config import MODELS_EXPERIMENTAL, MODELS_STABLE
from config import DEFAULT_MODEL

MODELS = MODELS_STABLE if USE_STABLE_MODELS else MODELS_EXPERIMENTAL


# Create the main Blueprint
main_bp = Blueprint('main', __name__)

# Before request handler to set session_id
@main_bp.before_request
def before_request():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    g.session_id = session['session_id']

# Main index route that serves the app with configuration
@main_bp.route('/')
def index():
    """Serve the index page with configuration."""
    return serve_index_with_config()

# Function to serve the index with embedded configuration
def serve_index_with_config():
    """
    Serve the index.html with dynamically embedded configuration.
    
    Returns:
        Rendered HTML template with configuration
    """
    # Ensure models are loaded
    ensure_openrouter_models()
    
    # Create model info for frontend
    model_info = []
    for model_name in MODELS:
        output_cost = get_1m_output_cost(model_name)
        model_info.append({
            "id": model_name,
            "name": model_name.split("/")[-1],
            "output_cost_per_1m": output_cost
        })
    
    # Get data about all available models
    all_models_data = openrouter_models_cache.get("models", [])
    
    # Find the matching model details
    detailed_model_info = []
    for model in model_info:
        model_id = model["id"]
        details = next((m for m in all_models_data if m.get("id") == model_id), {})
        
        context_length = details.get("context_length", 0)
        pricing = details.get("pricing", {})
        input_cost = pricing.get("prompt", 0) * 1_000_000 if pricing else 0
        output_cost = pricing.get("completion", 0) * 1_000_000 if pricing else 0
        
        detailed_model_info.append({
            "id": model_id,
            "name": model["name"],
            "context_length": context_length,
            "input_cost_per_1m": input_cost,
            "output_cost_per_1m": output_cost
        })
    
    # Static files path for the frontend
    static_path = "/static" if os.path.exists("static") else ""
    
    # Render the template with config
    return render_template(
        'index.html', 
        models=detailed_model_info,
        default_model=DEFAULT_MODEL,
        static_path=static_path
    )

# API route for title generation and summary
@main_bp.route('/api/title_summary', methods=['POST'])
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
    
    # Generate title and summary logic here...
    # (For now, returning placeholders)
    return jsonify({
        "title": "Generated Title",
        "summary": "Generated Summary"
    })

# API route for chat
@main_bp.route('/api/chat', methods=['POST'])
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
        
    # Append the user's question to history
    history.append({"role": "user", "content": question})
    
    # Summarize history to manage context length
    messages = summarize_history(history, max_chars=2000)
    
    if DEBUG_MESSAGES:
        print(f"[api_chat] question_length={len(question)}")
        print(f"[api_chat] model={selected_model!r}")
        print(f"[api_chat] history_count={len(history)}")
    
    # Create streaming response
    return Response(
        stream_with_context(generate_chat_response(selected_model, messages)),
        mimetype='text/plain'
    )

# Route for serving static React files
@main_bp.route('/<path:path>')
def serve_react_app(path):
    """
    Serve React app static files.
    
    Args:
        path: Path to the static file
        
    Returns:
        Static file or index.html for client-side routes
    """
    # Check if path exists as a static file
    static_folder = main_bp.static_folder or "frontend/build"
    static_file_path = Path(static_folder) / path
    
    if static_file_path.exists() and static_file_path.is_file():
        return send_from_directory(static_folder, path)
        
    # Otherwise serve the main app shell
    return serve_index_with_config()

# Function to register all blueprints
def register_blueprints(app):
    """
    Register all blueprints with the Flask app.
    
    Args:
        app: Flask application instance
    """
    # Register the main blueprint
    app.register_blueprint(main_bp)
    
    # Import and register the translation blueprint
    from translation_api import init_translation_api
    init_translation_api(app)
