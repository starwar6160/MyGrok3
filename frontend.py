"""
Frontend serving module for MyGrok3.

This module handles serving static files and frontend routes.
"""
from pathlib import Path
from flask import Blueprint, send_from_directory, render_template

from openrouter_manager import (
    ensure_openrouter_models, 
    get_1m_output_cost,
    openrouter_models_cache
)
import logging_config

# Configure logger
logger = logging_config.configure_logger(__name__)

# Flag to switch between experimental and stable model lists
import os
USE_STABLE_MODELS = os.environ.get('USE_STABLE_MODELS') == 'true'

# Model configurations
from models_config import MODELS_EXPERIMENTAL, MODELS_STABLE

MODELS = MODELS_STABLE if USE_STABLE_MODELS else MODELS_EXPERIMENTAL
DEFAULT_MODEL = MODELS[0]

# Create frontend blueprint
frontend_bp = Blueprint(
    'frontend', 
    __name__, 
    static_folder='frontend/build',
    template_folder='templates'
)

@frontend_bp.route('/')
def index():
    """
    Serve the main index page with configuration.
    
    Returns:
        Rendered HTML template with configuration
    """
    return serve_index_with_config()

def serve_index_with_config():
    """
    Serve the index.html with dynamically embedded configuration.
    
    Returns:
        Rendered HTML template with configuration
    """
    # Ensure models are loaded
    ensure_openrouter_models()
    logger.debug("Serving index page with OpenRouter models configuration")
    
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
    
    logger.info(f"Serving frontend with {len(detailed_model_info)} models configured")
    
    # Render the template with config
    return render_template(
        'index.html', 
        models=detailed_model_info,
        default_model=DEFAULT_MODEL,
        static_path=static_path
    )

@frontend_bp.route('/<path:path>')
def serve_static(path):
    """
    Serve static files from the frontend build directory.
    
    Args:
        path: Path to the static file
        
    Returns:
        Static file or index.html for client-side routes
    """
    logger.debug(f"Attempting to serve static file: {path}")
    
    # Serve static files directly if they exist
    static_file_path = Path(frontend_bp.static_folder) / path
    if static_file_path.exists() and static_file_path.is_file():
        return send_from_directory(frontend_bp.static_folder, path)
    
    # For any other path (including client-side routes), serve the main app shell
    logger.debug(f"Static file {path} not found, serving index instead")
    return serve_index_with_config()

def register_blueprint(app):
    """
    Register the frontend blueprint with the Flask application.
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(frontend_bp)
    logger.info("Frontend blueprint registered")
