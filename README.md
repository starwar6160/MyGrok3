# MyGrok3

MyGrok3 is a Flask-based web application that provides an interface to interact with various AI models through the OpenRouter API.

## Refactored Structure

The codebase has been refactored to improve modularity, maintainability, and organization:

### Core Modules

- `app.py` - Main application entry point that initializes and runs the Flask app
- `routes.py` - Organizes all Flask routes using blueprints
- `chat_handler.py` - Handles all chat functionality with LLM models
- `cache_manager.py` - Manages caching of LLM responses
- `conversation_utils.py` - Utilities for handling conversation history and summarization
- `openrouter_manager.py` - Manages OpenRouter model information and pricing
- `translation_api.py` - Implements translation functionality
- `cost_calculator.py` - Handles cost calculation and tracking
- `response_utils.py` - Utilities for processing responses
- `logging_config.py` - Configuration for logging

### Running the Application

```bash
# Set environment variables
export OPENAI_API_KEY=your_api_key
export FLASK_APP=app.py

# Run with stable models
export USE_STABLE_MODELS=true
flask run -p 5005 -h 0.0.0.0

# Or run with experimental models
export USE_STABLE_MODELS=false
flask run -p 5005 -h 0.0.0.0
```

### Features

- Chat interface with multiple AI models
- Cost tracking and optimization
- Translation capabilities
- Response streaming
- History summarization to manage context length
- Caching to reduce API costs

## Development

The refactored structure separates concerns into dedicated modules, making the codebase easier to maintain and extend.
