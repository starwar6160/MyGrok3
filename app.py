"""
MyGrok3 main application module.

This is the main entry point for the MyGrok3 application, integrating all the
refactored components.
"""
import os
import socket
import uuid
from flask import Flask, g, session
from flask_cors import CORS

import logging_config
from chat_api import register_blueprint as register_chat_api
from frontend import register_blueprint as register_frontend
from translation_api import init_translation_api as register_translation_api
from utils.price_utils import price_api
from session_store import get_session_store
from cost_calculator import initialize_prices

# Configure logger
logger = logging_config.configure_logger(__name__)

# 初始化价格表，防止footer金额为0
try:
    initialize_prices()
    logger.info("[APP INIT] Model price table initialized.")
except Exception as e:
    logger.error(f"[APP INIT] Failed to initialize model price table: {e}")

def create_app():
    """
    Create and configure the Flask application.
    
    Returns:
        Configured Flask application
    """
    # Initialize Flask app with static folder
    app = Flask(
        __name__, 
        static_folder="frontend/build", 
        template_folder="templates"
    )
    
    # Configure app
    app.secret_key = os.getenv('SECRET_KEY', 'your_secret_key')  # Replace in production
    
    # Initialize session store singleton
    store = get_session_store()
    logger.info("Session store initialized")
    
    # Enable CORS
    try:
        CORS(app)
        logger.info("CORS enabled for the application")
    except ImportError:
        logger.warning("Flask-CORS not installed, CORS will not be enabled")
    
    # Register before_request handler to set session_id
    @app.before_request
    def before_request():
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
            logger.debug(f"Created new session: {session['session_id']}")
        g.session_id = session['session_id']
    
    # Register all blueprints
    register_chat_api(app)
    register_frontend(app)
    register_translation_api(app)
    app.register_blueprint(price_api)
    
    logger.info("All blueprints registered")
    
    return app

def find_free_port(start_port=5000, max_tries=10):
    """
    Find an available port for the application.
    
    Args:
        start_port: Port to start checking from
        max_tries: Maximum number of ports to check
        
    Returns:
        Available port number
        
    Raises:
        RuntimeError: If no free port is found
    """
    port = start_port
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('0.0.0.0', port)) != 0:
                return port
            port += 1
    raise RuntimeError("No free port found in range.")

# Only run the app when this file is executed directly
if __name__ == "__main__":
    app = create_app()
    
    # Determine port
    port = int(os.environ.get('PORT', find_free_port()))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    logger.info(f"Starting MyGrok3 on port {port}, debug={debug}")
    app.run(host='0.0.0.0', port=port, debug=debug)
