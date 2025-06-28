# MyGrok3

A modular and extensible web UI for Claude and OpenAI models via OpenRouter.

## Features

- Local / offline LLM support
- Thread-safe session management with auto-cleanup
- Ephemeral storage, persistence per browser session
- Optional persistent storage via Catalog in `catalog-mode` branch
- Full chat history with ability to revisit past exchanges
- Stream responses for better UX
- Use OpenRouter API to access models
- Better code formatting and syntax highlighting
- Light/Dark mode support
- Speech input (Chrome/Edge)
- Function calling for current location
- Better mobile responsive UX
- Comprehensive usage tracking and cost calculation
- Modular architecture for easy testing and extension

## Architecture

MyGrok3 follows a modular architecture with clear separation of concerns:

```
MyGrok3/
├── app.py                 # Main application entry point
├── chat_api.py            # Chat-related API endpoints and routes
├── chat_handler.py        # LLM interaction and streaming logic
├── frontend.py            # Frontend serving blueprint
├── openrouter_manager.py  # OpenRouter model management
├── session_store.py       # Thread-safe global session state
├── translation_api.py     # Translation service API
├── utils/
│   ├── __init__.py       
│   └── message_utils.py   # Utilities for message processing
├── tests/                 # Unit and integration tests
└── frontend/              # React frontend code
```

### Key Components

- **Session Store**: Thread-safe singleton for managing all session data including messages, token counts, and costs
- **Chat Handler**: Encapsulates streaming and non-streaming LLM calls
- **Message Utilities**: Functions for message validation, history summarization, and token counting
- **OpenRouter Manager**: Model fetching, pricing, and caching
- **Blueprint Organization**: Separate blueprints for chat API, frontend, and translation

## Setup

1. Clone this repo
2. Set `OPENAI_API_KEY` to your OpenRouter API key
3. Run `pip install -r requirements.txt`
4. Run `python app.py`
5. Navigate to http://127.0.0.1:5000/

## Development

### Backend

The Flask backend is organized into blueprints and modules. To run tests:

```bash
python -m unittest discover -s tests
```

### Frontend

App uses React frontend with TypeScript.

To develop:

```bash
cd frontend
npm install
npm start
```

This will start the dev server on port 3000, proxying API calls to the Flask backend on port 5000.

To build production assets:

```bash
cd frontend
npm run build
```

## Environment Variables

- `OPENAI_API_KEY` - Your OpenRouter API key (required)
- `USE_STABLE_MODELS` - Set to `true` to use only stable models list (optional)
- `FLASK_APP` - Set to `app.py` (default for Flask)
- `FLASK_DEBUG` - Set to `true` for debug mode (optional)
- `SECRET_KEY` - Flask session encryption key (generated if not provided)
- const CLEANUP_MAX_AGE_HOURS = 4; // Conversations older than this will be cleaned
- const CLEANUP_MIN_AI_REPLIES = 5; // if they have fewer than this many AI replies

## API Endpoints

- `/api/chat` - Main chat endpoint (POST)
- `/api/title_summary` - Generate title and summary for a conversation (POST)
- `/api/session_stats` - Get session usage statistics (GET)
- `/api/translate` - Translation service (POST)

## Future Improvements

- Persistent storage options (Redis) for session and cache data
- Additional unit and integration test coverage
- More cost-effective tokenizer implementation

## Running the Application

```bash
# Set environment variables
export OPENAI_API_KEY=your_api_key
export FLASK_APP=app.py

# Run with stable models
export USE_STABLE_MODELS=true
flask run -p 5005 -h 0.0.0.0

# Or run with experimental models
screen
source ~/tmp/venv/bin/activate
export USE_STABLE_MODELS=false
flask run -p 5005 -h 0.0.0.0
### Features

- Chat interface with multiple AI models
- Cost tracking and optimization
- Translation capabilities
- Response streaming
- History summarization to manage context length
- Caching to reduce API costs

## Development

The refactored structure separates concerns into dedicated modules, making the codebase easier to maintain and extend.
