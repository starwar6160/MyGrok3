"""
Centralized logging configuration for the application.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def configure_logger(name: str, log_level=logging.INFO) -> logging.Logger:
    """
    Configure and return a logger with consistent settings.
    
    Args:
        name: Name of the logger (usually __name__)
        log_level: Minimum log level to capture
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Create logs directory if it doesn't exist
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Add handlers if not already added
    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File handler with rotation
        file_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger
