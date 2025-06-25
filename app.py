"""
MyGrok3 main application module.

This is the main entry point for the MyGrok3 application, integrating all the
refactored components.
"""
import os
import socket
from flask import Flask
from flask_cors import CORS

from MyGrok3 import logging_config
from MyGrok3.routes import register_blueprints

# Configure logger
logger = logging_config.configure_logger(__name__)

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
    
    # Enable CORS
    try:
        CORS(app)
        logger.info("CORS enabled for the application")
    except ImportError:
        logger.warning("Flask-CORS not installed, CORS will not be enabled")
    
    # Register all blueprints
    register_blueprints(app)
    
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
