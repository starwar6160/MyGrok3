import openai
import os
import hashlib
import json
import socket
from flask import Flask, render_template, request, Response, stream_with_context, send_from_directory, jsonify
from pathlib import Path
import redis
from datetime import datetime, timedelta
import uuid
import time
import threading
import logging
from functools import wraps

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG to see all messages
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Global flag to track Redis availability
REDIS_AVAILABLE = True
REDIS_HOST = os.getenv('REDIS_HOST', 'mredis')  # 使用容器名
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))

class FallbackDict(dict):
    """A dictionary that logs when fallback is used"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logged_warning = False
    
    def _log_fallback(self):
        if not self.logged_warning:
            logger.warning("Using in-memory fallback storage. Data will be lost on server restart.")
            self.logged_warning = True
    
    def get(self, key, default=None):
        self._log_fallback()
        return super().get(key, default)
    
    def set(self, key, value, ex=None):
        self._log_fallback()
        super().__setitem__(key, value)
        return True
    
    def delete(self, key):
        self._log_fallback()
        if key in self:
            del self[key]
            return 1
        return 0

# Global variables for Redis state management
_redis_available = False
_redis_last_check = 0
_redis_check_interval = 60  # seconds
_using_redis = False  # Whether we're currently using Redis as primary storage
_redis_lock = threading.Lock()

# Initialize in-memory fallback storage
fallback_storage = FallbackDict()

def sync_to_redis():
    """
    Sync all data from in-memory storage to Redis.
    This is called when Redis becomes available.
    """
    global _using_redis
    
    try:
        logger.info("Attempting to get Redis connection...")
        redis_conn = get_redis_connection(force_redis=True)
        if isinstance(redis_conn, FallbackDict):
            logger.error("Failed to get Redis connection: FallbackDict returned")
            return False  # Redis not available
            
        logger.info("Got Redis connection, getting in-memory storage...")
        # Get in-memory storage
        in_memory = get_redis_connection()
        if not isinstance(in_memory, FallbackDict):
            logger.info("Already using Redis, no need to sync")
            return False  # Already using Redis
            
        with _redis_lock:
            logger.info("Acquired lock, starting sync...")
            # Get all conversation IDs
            conversation_ids = in_memory.get("conversations", [])
            if not isinstance(conversation_ids, list):
                logger.warning(f"conversation_ids is not a list: {conversation_ids}")
                conversation_ids = []
            
            logger.info(f"Found {len(conversation_ids)} conversations to sync")
            
            # Sync each conversation and its messages
            for i, conv_id in enumerate(conversation_ids, 1):
                try:
                    logger.debug(f"Syncing conversation {i}/{len(conversation_ids)}: {conv_id}")
                    # Sync conversation data
                    conv_key = f'conversation:{conv_id}'
                    conv_data = in_memory.get(conv_key, {})
                    if conv_data:
                        if isinstance(conv_data, str):
                            conv_data = json.loads(conv_data)
                        logger.debug(f"Setting conversation data for {conv_key}")
                        redis_conn.hmset(conv_key, conv_data)
                        redis_conn.expire(conv_key, REDIS_EXPIRE_SECONDS)
                    
                    # Sync messages
                    messages_key = f'messages:{conv_id}'
                    messages = in_memory.get(messages_key, [])
                    if messages:
                        logger.debug(f"Syncing {len(messages)} messages for {messages_key}")
                        # Delete any existing messages in Redis
                        redis_conn.delete(messages_key)
                        # Add all messages
                        for msg in messages:
                            if isinstance(msg, str):
                                msg_data = json.loads(msg)
                                redis_conn.rpush(messages_key, json.dumps(msg_data))
                            else:
                                redis_conn.rpush(messages_key, json.dumps(msg))
                        redis_conn.expire(messages_key, REDIS_EXPIRE_SECONDS)
                except Exception as e:
                    logger.error(f"Error syncing conversation {conv_id}: {e}", exc_info=True)
                    continue  # Continue with next conversation even if one fails
            
            # Sync conversations list
            if conversation_ids:
                try:
                    logger.info("Syncing conversations list...")
                    redis_conn.delete("conversations")
                    redis_conn.rpush("conversations", *conversation_ids)
                    redis_conn.expire("conversations", REDIS_EXPIRE_SECONDS)
                    logger.info("Successfully synced conversations list")
                except Exception as e:
                    logger.error(f"Error syncing conversations list: {e}", exc_info=True)
                    return False
            
            # Mark that we're now using Redis
            _using_redis = True
            logger.info("Successfully completed Redis sync")
            return True
            
    except Exception as e:
        logger.error(f"Critical error in sync_to_redis: {e}", exc_info=True)
        return False

def check_redis_availability():
    """Check if Redis is available and sync data if it becomes available"""
    global _redis_available, _redis_last_check, _using_redis, _redis_check_interval
    
    current_time = time.time()
    time_since_last_check = current_time - _redis_last_check
    
    # Only proceed if enough time has passed since last check
    if time_since_last_check < _redis_check_interval and not _redis_available:
        return _redis_available
    
    _redis_last_check = current_time
    
    # If we're already using Redis, just verify the connection
    if _using_redis:
        try:
            conn = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=1, socket_keepalive=True)
            conn.ping()
            if not _redis_available:  # Only log on state change
                logger.info("Connected to Redis successfully")
            _redis_available = True
            return True
        except Exception as e:
            _redis_available = False
            _using_redis = False  # Fall back to in-memory storage
            logger.error(f"Lost connection to Redis: {e}")
            return False
    
    # If we're not using Redis yet, try to connect and sync
    try:
        # Try both localhost and 127.0.0.1
        for host in ['localhost', '127.0.0.1']:
            try:
                conn = redis.Redis(host=host, port=6379, db=0, socket_connect_timeout=2, socket_keepalive=True)
                conn.ping()
                logger.info(f"Successfully connected to Redis at {host}:6379")
                break
            except Exception as e:
                logger.debug(f"Failed to connect to Redis at {host}:6379: {e}")
                if host == '127.0.0.1':  # If both attempts failed
                    raise
        
        if not _redis_available:  # Only log on state change
            logger.info("Redis is now available, attempting to sync data...")
            
        if sync_to_redis():
            logger.info("Successfully synced data to Redis")
            _redis_available = True
            _using_redis = True
            _redis_check_interval = 60  # Reset to normal check interval
            return True
        else:
            # Increase check interval on failure (exponential backoff, max 5 minutes)
            _redis_check_interval = min(300, _redis_check_interval * 2)
            logger.warning(f"Failed to sync data to Redis, will retry in {_redis_check_interval} seconds")
            return False
            
    except redis.ConnectionError as e:
        if _redis_available:  # Only log on state change
            logger.error(f"Redis connection failed: {e}")
        _redis_available = False
        # Increase check interval on failure (exponential backoff, max 5 minutes)
        _redis_check_interval = min(300, _redis_check_interval * 2)
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking Redis: {e}")
        _redis_available = False
        _redis_check_interval = min(300, _redis_check_interval * 2)
        return False

# Start the Redis monitoring thread
def start_redis_monitor():
    def monitor():
        while True:
            try:
                check_redis_availability()
            except Exception as e:
                logger.error(f"Error in Redis monitor thread: {e}")
            finally:
                # Always sleep to prevent tight loops on error
                time.sleep(_redis_check_interval)
    
    thread = threading.Thread(target=monitor, daemon=True, name="RedisMonitor")
    thread.start()
    return thread

# Start the monitor when the module loads
_redis_monitor_thread = start_redis_monitor()

# Log initial storage status
def log_storage_status():
    if _redis_available and _using_redis:
        logger.info("Using Redis as the primary storage")
    else:
        logger.info("Using in-memory storage (Redis is not available)")

# Initial status log
log_storage_status()

# Update status when Redis becomes available
_original_sync_to_redis = sync_to_redis
def wrapped_sync_to_redis():
    result = _original_sync_to_redis()
    if result:
        log_storage_status()
    return result
sync_to_redis = wrapped_sync_to_redis

def redis_available():
    """
    Check if Redis is available by attempting to get a connection.
    Updates the global _redis_available state.
    """
    global _redis_available
    
    # If we think Redis is available, verify it with a quick ping
    if _redis_available:
        try:
            # Try to get a connection with a short timeout
            conn = get_redis_connection(force_redis=True)
            if isinstance(conn, FallbackDict):
                _redis_available = False
                return False
            conn.ping()
            return True
        except Exception as e:
            logger.debug(f"Redis ping failed: {e}")
            _redis_available = False
            return False
    
    # If we don't think Redis is available, do a thorough check
    try:
        conn = get_redis_connection(force_redis=True)
        if not isinstance(conn, FallbackDict):
            _redis_available = True
            return True
        return False
    except Exception as e:
        _redis_available = False
        logger.debug(f"Redis availability check failed: {e}")
        return False

def get_redis_connection(force_redis=False):
    """
    Get storage connection. Uses in-memory storage by default, or Redis if available and we've switched to it.
    """
    global _using_redis, _redis_available, _redis_connection
    
    # If we're not forcing Redis and not in Redis mode, use in-memory fallback
    if not force_redis and not _using_redis:
        logger.debug("Using in-memory storage (not forcing Redis and not in Redis mode)")
        return FallbackDict()
    
    # If we already have a working Redis connection, return it
    if _redis_connection is not None and _redis_available:
        try:
            _redis_connection.ping()
            return _redis_connection
        except:
            _redis_available = False
            _redis_connection = None
    
    # Try to establish a new Redis connection
    logger.debug(f"Getting Redis connection (force_redis={force_redis}, _using_redis={_using_redis})")
    
    # Use the configured Redis host and port
    try:
        logger.debug(f"Attempting to connect to Redis at {REDIS_HOST}:{REDIS_PORT}")
        conn = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=0,
            socket_connect_timeout=2,
            socket_keepalive=True,
            socket_keepalive_options={
                socket.TCP_KEEPIDLE: 60,   # Start sending keepalive after 60s of idle
                socket.TCP_KEEPINTVL: 10,  # Send keepalive every 10s
                socket.TCP_KEEPCNT: 6      # Consider dead after 6 failed keepalives
            },
            retry_on_timeout=True,
            health_check_interval=30,
            decode_responses=False  # Keep raw bytes for compatibility
        )
        conn.ping()
        _redis_connection = conn
        _redis_available = True
        _using_redis = True
        logger.info(f"Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        return conn
    except redis.ConnectionError as e:
        logger.warning(f"Connection error to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}")
    except redis.RedisError as e:
        logger.error(f"Redis error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error connecting to Redis: {e}", exc_info=True)
    
    # If we get here, connection failed
    _redis_available = False
    _using_redis = False
    logger.warning("Using in-memory fallback storage.")
    return FallbackDict()

# Determine if running inside Docker
IS_DOCKER = os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER", False)

if IS_DOCKER:
    DATA_DIR = "/app/data"
else:
    # Use a local data directory if not in Docker
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

CONVERSATIONS_DIR = os.path.join(DATA_DIR, "conversations")

# Ensure the data directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

# === React 静态页面 ===
app = Flask(__name__, static_folder="frontend/build", template_folder="frontend/build")

# 允许跨域
try:
    from flask_cors import CORS
    CORS(app)
except ImportError:
    pass  # 如果没装CORS，先不报错

@app.route('/')
@app.route('/<path:path>')
def serve_react(path='index.html'):
    # Handle API routes
    if path.startswith('api/'):
        return 'Not Found', 404
    
    # Handle static files
    if path != 'index.html' and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    
    # Serve index.html for all other routes to support client-side routing
    return send_from_directory(app.template_folder, 'index.html')

@app.route("/", methods=["GET", "POST"])
def index():
    answer = None
    error = None
    question = ""
    selected_model = "grok-3-mini"  # Default model

    # 流式API: POST JSON，支持上下文和缓存
    if request.method == "POST" and request.content_type and request.content_type.startswith("application/json"):
        data = request.get_json()
        question = data.get("question", "").strip()
        selected_model = data.get("model", "grok-3-mini")
        history = data.get("history", [])  # 前端需传递历史消息（[{role, content}]）
        conversation_id = data.get("conversation_id") or "default"
        if not question:
            return Response("Please enter a question.", mimetype="text/plain"), 400
        # 拼接历史+当前
        history.append({"role": "user", "content": question})
        messages = summarize_history(history, max_chars=2000)
        # --- 保存用户消息 ---
        import time
        
        def stream_gen():
            assistant_content = ""
            for chunk in get_llm_cached(selected_model, messages, stream=True):
                assistant_content += chunk
                yield chunk
            # --- 保存AI回复 ---
            
        return Response(stream_with_context(stream_gen()), mimetype='text/plain')

    # 普通表单POST（无历史，仅单轮）
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        selected_model = request.form.get("model", "grok-3-mini")
        if not question:
            error = "Please enter a question."
        else:
            messages = [{"role": "user", "content": question}]
            answer = get_llm_cached(selected_model, messages)
    print('[FLASK] / index page response:', locals())
    return render_template(
        "index.html",
        answer=answer,
        error=error,
        question=question,
        selected_model=selected_model
    )

def initialize_openai_client():
    """Initialize the OpenAI client with proper error handling and logging."""
    try:
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable is not set")
            
        logger.info("Initializing OpenAI client...")
        client = openai.OpenAI(
            base_url="https://api.x.ai/v1",
            api_key=api_key,
            timeout=30.0  # Add a timeout for API requests
        )
        
        # Test the connection with a simple request
        logger.info("Testing OpenAI client connection...")
        client.models.list()  # This will raise an exception if the API key is invalid
        
        logger.info("Successfully initialized and tested OpenAI client")
        return client
        
    except Exception as e:
        error_msg = f"Failed to initialize OpenAI client: {type(e).__name__} - {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None

# Initialize the client
try:
    client = initialize_openai_client()
    if client is None:
        logger.error("OpenAI client initialization failed - chat functionality will not work")
        # Create a dummy client to prevent attribute errors
        client = type('DummyClient', (), {'chat': type('DummyChat', (), {
            'completions': type('DummyCompletions', (), {
                'create': lambda *args, **kwargs: {'choices': [{'message': {'content': 'Error: OpenAI client not properly initialized. Please check the logs.'}}]}
            })
        })})()
    else:
        logger.info("OpenAI client is ready to use")
except Exception as e:
    logger.error(f"Unexpected error during OpenAI client initialization: {e}", exc_info=True)
    client = None

# Redis keys for conversations and messages
CONVERSATIONS_KEY = "conversations"
# Expiration time in seconds (7 days)
REDIS_EXPIRE_SECONDS = 7 * 24 * 60 * 60  # 7 days in seconds

# LLM 缓存函数
def get_llm_cache(prompt_hash):
    """Get cached LLM response if available"""
    try:
        # First try in-memory storage
        cache_key = f'llm_cache:{prompt_hash}'
        redis_conn = get_redis_connection()
        
        if isinstance(redis_conn, FallbackDict):
            # Get from in-memory storage
            return redis_conn.get(cache_key)
        else:
            # Fall back to Redis if explicitly requested
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
                if not isinstance(redis_conn_redis, FallbackDict):
                    return redis_conn_redis.get(cache_key)
            except Exception as e:
                logger.warning(f"Failed to get from Redis cache: {e}")
        
        return None
    except Exception as e:
        logger.error(f"Error getting LLM cache: {e}")
        return None

def set_llm_cache(prompt_hash, response):
    """Cache LLM response"""
    try:
        cache_key = f'llm_cache:{prompt_hash}'
        redis_conn = get_redis_connection()
        
        # Save to in-memory storage
        if isinstance(redis_conn, FallbackDict):
            redis_conn[cache_key] = response
        
        # If Redis is available, also cache there
        if redis_available():
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
                if not isinstance(redis_conn_redis, FallbackDict):
                    redis_conn_redis.setex(cache_key, timedelta(days=7), response)
            except Exception as e:
                logger.warning(f"Failed to set Redis cache: {e}")
        
        return response
    except Exception as e:
        logger.error(f"Error setting LLM cache: {e}")
        return None

@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    """Get all conversations from in-memory storage by default, with Redis as fallback"""
    try:
        # First try to get from in-memory storage
        redis_conn = get_redis_connection()
        conversations = []
        
        # Get conversations from in-memory storage
        if isinstance(redis_conn, FallbackDict):
            for key in list(redis_conn.keys()):
                if key.startswith('conversation:'):
                    try:
                        conv_data = redis_conn[key]
                        if isinstance(conv_data, dict):
                            conversations.append({
                                'id': key.split(':', 1)[1],
                                'title': conv_data.get('title', 'New Conversation'),
                                'created_at': conv_data.get('created_at', datetime.now().isoformat()),
                                'updated_at': conv_data.get('updated_at', datetime.now().isoformat())
                            })
                    except Exception as e:
                        logger.error(f"Error processing in-memory conversation {key}: {e}")
        
        # If no conversations in memory and Redis is available, try Redis
        if not conversations and redis_available():
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
                if not isinstance(redis_conn_redis, FallbackDict):
                    for key in redis_conn_redis.scan_iter('conversation:*'):
                        try:
                            conv_data = redis_conn_redis.hgetall(key)
                            if conv_data:
                                # Add to conversations list
                                conversations.append({
                                    'id': key.decode('utf-8').split(':', 1)[1],
                                    'title': conv_data.get(b'title', b'New Conversation').decode('utf-8'),
                                    'created_at': conv_data.get(b'created_at', datetime.now().isoformat().encode('utf-8')).decode('utf-8'),
                                    'updated_at': conv_data.get(b'updated_at', datetime.now().isoformat().encode('utf-8')).decode('utf-8')
                                })
                                
                                # Cache in memory for future use
                                if isinstance(redis_conn, FallbackDict):
                                    conv_id = key.decode('utf-8').split(':', 1)[1]
                                    redis_conn[f'conversation:{conv_id}'] = {
                                        'id': conv_id,
                                        'title': conv_data.get(b'title', b'New Conversation').decode('utf-8'),
                                        'created_at': conv_data.get(b'created_at', datetime.now().isoformat().encode('utf-8')).decode('utf-8'),
                                        'updated_at': conv_data.get(b'updated_at', datetime.now().isoformat().encode('utf-8')).decode('utf-8')
                                    }
                        except Exception as e:
                            logger.error(f"Error processing Redis conversation {key}: {e}")
            except Exception as e:
                logger.warning(f"Failed to get conversations from Redis: {e}")
        
        # Sort by updated_at in descending order
        conversations.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        return jsonify(conversations)
    except Exception as e:
        logger.error(f"Error getting conversations: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversations', methods=['POST'])
def create_conversation():
    try:
        # Always use in-memory storage by default
        redis_conn = get_redis_connection()
        
        # Check if Redis is available for syncing
        redis_available_flag = redis_available()
        redis_conn_redis = None
        if redis_available_flag:
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
            except Exception as e:
                logger.warning(f"Failed to connect to Redis for conversation creation: {e}")
                redis_available_flag = False
        
        # Create conversation data
        conversation_id = str(uuid.uuid4())
        title = "New Chat"  # Default title that will be updated later
        created_at = datetime.now().isoformat()
        
        # Prepare conversation data
        conversation_data = {
            'id': conversation_id,
            'title': title,
            'created_at': created_at,
            'updated_at': created_at
        }
        
        # Save to in-memory storage
        if isinstance(redis_conn, FallbackDict):
            # Save conversation data
            redis_conn[f'conversation:{conversation_id}'] = conversation_data
            # Initialize empty messages list
            redis_conn[f'messages:{conversation_id}'] = []
            
            # Add to conversations list
            conversations = redis_conn.get(CONVERSATIONS_KEY, [])
            if not isinstance(conversations, list):
                conversations = []
            if conversation_id not in conversations:
                conversations.append(conversation_id)
                redis_conn[CONVERSATIONS_KEY] = conversations
        
        # If Redis is available, also sync to Redis
        if redis_available_flag and redis_conn_redis and not isinstance(redis_conn_redis, FallbackDict):
            try:
                # Save conversation data to Redis
                redis_conn_redis.hmset(
                    f'conversation:{conversation_id}',
                    {
                        'title': title,
                        'created_at': created_at,
                        'updated_at': created_at
                    }
                )
                # Set expiration
                redis_conn_redis.expire(f'conversation:{conversation_id}', REDIS_EXPIRE_SECONDS)
                
                # Create empty messages list in Redis
                messages_key = f'messages:{conversation_id}'
                redis_conn_redis.rpush(messages_key, '')  # Add empty message to create the list
                redis_conn_redis.expire(messages_key, REDIS_EXPIRE_SECONDS)
                
                # Add to conversations list in Redis
                redis_conn_redis.lpush(CONVERSATIONS_KEY, conversation_id)
                redis_conn_redis.expire(CONVERSATIONS_KEY, REDIS_EXPIRE_SECONDS)
            except Exception as e:
                logger.warning(f"Failed to sync new conversation to Redis: {e}")
        
        return jsonify({
            'id': conversation_id,
            'title': title,
            'created_at': created_at,
            'updated_at': created_at
        }), 201
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Get a specific conversation"""
    try:
        # First try to get from in-memory storage
        redis_conn = get_redis_connection()
        conv_data = {}
        
        # Try to get from in-memory storage
        if isinstance(redis_conn, FallbackDict):
            conv_data = redis_conn.get(f'conversation:{conversation_id}', {})
            if not isinstance(conv_data, dict):
                conv_data = {}
        
        # If not found in memory and Redis is available, try Redis
        if not conv_data and redis_available():
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
                if not isinstance(redis_conn_redis, FallbackDict):
                    redis_data = redis_conn_redis.hgetall(f'conversation:{conversation_id}')
                    if redis_data:
                        conv_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in redis_data.items()}
                        # Cache in memory for future use
                        if isinstance(redis_conn, FallbackDict):
                            redis_conn[f'conversation:{conversation_id}'] = conv_data
            except Exception as e:
                logger.warning(f"Failed to get conversation from Redis: {e}")
        
        if not conv_data:
            return jsonify({'error': 'Conversation not found'}), 404
            
        return jsonify({
            'id': conversation_id,
            'title': conv_data.get('title', 'Untitled'),
            'created_at': conv_data.get('created_at', ''),
            'updated_at': conv_data.get('updated_at', ''),
            'messages': []  # Messages are loaded separately
        })
    except Exception as e:
        logger.error(f"Error getting conversation {conversation_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversations/<conversation_id>/messages', methods=['GET'])
def get_conversation_messages_list(conversation_id):
    """Get all messages for a specific conversation"""
    try:
        # First try to get from in-memory storage
        redis_conn = get_redis_connection()
        messages = []
        
        # Try to get from in-memory storage
        if isinstance(redis_conn, FallbackDict):
            message_list = redis_conn.get(f'messages:{conversation_id}', [])
            if not isinstance(message_list, list):
                if message_list == '':  # Handle empty string case
                    message_list = []
                else:
                    message_list = [message_list] if message_list else []
        
        # If no messages in memory and Redis is available, try Redis
        if (not messages or len(messages) == 0) and redis_available():
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
                if not isinstance(redis_conn_redis, FallbackDict):
                    redis_messages = redis_conn_redis.lrange(f'messages:{conversation_id}', 0, -1)
                    if redis_messages:
                        message_list = []
                        for msg in redis_messages:
                            try:
                                msg_data = json.loads(msg.decode('utf-8'))
                                if isinstance(msg_data, dict) and 'content' in msg_data and 'role' in msg_data:
                                    message_list.append(msg_data)
                            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                                logger.error(f"Error decoding Redis message: {e}")
                        
                        # Cache in memory for future use
                        if isinstance(redis_conn, FallbackDict):
                            redis_conn[f'messages:{conversation_id}'] = message_list
            except Exception as e:
                logger.warning(f"Failed to get messages from Redis: {e}")
        
        # Process messages
        for msg in message_list:
            try:
                # In in-memory mode, messages might already be dictionaries
                if isinstance(msg, str):
                    msg = json.loads(msg)
                
                # Ensure the message has all required fields
                if isinstance(msg, dict) and 'content' in msg and 'role' in msg:
                    messages.append(msg)
                else:
                    logger.warning(f"Skipping invalid message format: {msg}")
                    
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                logger.error(f"Error decoding message {msg}: {e}")
                continue
        
        # Ensure we have a proper list of message objects
        valid_messages = [
            {
                'id': msg.get('id', str(uuid.uuid4())),
                'conversation_id': conversation_id,
                'role': msg.get('role', ''),
                'content': msg.get('content', ''),
                'timestamp': msg.get('timestamp', datetime.now().isoformat())
            }
            for msg in messages
            if isinstance(msg, dict) and 'content' in msg and 'role' in msg
        ]
        
        return jsonify(valid_messages)
        
    except Exception as e:
        logger.error(f"Error getting messages for conversation {conversation_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    """Delete a conversation and its messages"""
    try:
        # Always use in-memory storage by default
        redis_conn = get_redis_connection()
        
        # Check if Redis is available for syncing
        redis_available_flag = redis_available()
        redis_conn_redis = None
        if redis_available_flag:
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
            except Exception as e:
                logger.warning(f"Failed to connect to Redis for deletion: {e}")
                redis_available_flag = False
        
        # Delete from in-memory storage
        if isinstance(redis_conn, FallbackDict):
            # Delete conversation data
            if f"conversation:{conversation_id}" in redis_conn:
                del redis_conn[f"conversation:{conversation_id}"]
            # Delete messages
            if f"messages:{conversation_id}" in redis_conn:
                del redis_conn[f"messages:{conversation_id}"]
            
            # Remove from conversations list
            conversations = redis_conn.get(CONVERSATIONS_KEY, [])
            if not isinstance(conversations, list):
                conversations = []
            if conversation_id in conversations:
                conversations.remove(conversation_id)
                redis_conn[CONVERSATIONS_KEY] = conversations
        
        # If Redis is available, also delete from Redis
        if redis_available_flag and redis_conn_redis:
            try:
                # Delete from Redis
                redis_conn_redis.delete(f"conversation:{conversation_id}")
                redis_conn_redis.delete(f"messages:{conversation_id}")
                redis_conn_redis.lrem(CONVERSATIONS_KEY, 0, conversation_id)
            except Exception as e:
                logger.warning(f"Failed to delete conversation from Redis: {e}")
        
        return jsonify({'message': 'Conversation deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/llm_cache', methods=['POST'])
def set_llm_cache_api():
    try:
        data = request.get_json()
        prompt_hash = data.get('hash')
        response_content = data.get('response')
        
        if not all([prompt_hash, response_content]):
            return jsonify({'message': 'Missing required fields'}), 400
            
        set_llm_cache(prompt_hash, response_content)
        return jsonify({'message': 'Cache set successfully'}), 201
    except Exception as e:
        logger.error(f"Error setting LLM cache: {e}")
        return jsonify({'message': 'Failed to set cache'}), 500

@app.route("/api/title_summary", methods=["POST"])
def api_title_summary():
    try:
        data = request.get_json()
        print('[FLASK] /api/title_summary received:', data)
        messages = data.get("messages", [])
        conversation_id = data.get("conversation_id")
        
        # Default title if we can't generate one
        default_title = "新会话"
        
        # Try to generate a title using the LLM
        try:
            prompt = (
                "请根据以下对话内容，自动归纳一个简明、概括性的标题（10字以内），只返回标题本身，不要加任何解释：\n"
                + '\n'.join(f"[{m.get('role','')}] {m.get('content','')}" for m in messages)
            )
            title = ask_grok("grok-3-mini", [{"role": "user", "content": prompt}])
            # 只取前10字，去除空白
            title = (title or default_title).strip().replace("\n", "").replace("：", ":")[:10]
        except Exception as e:
            logger.error(f"Error generating title with LLM: {e}")
            # Fallback to first user message or default
            first_user_msg = next((m.get('content', '') for m in messages if m.get('role') == 'user'), '')
            title = first_user_msg[:10] + ('...' if len(first_user_msg) > 10 else '') if first_user_msg else default_title
        
        print('[FLASK] /api/title_summary response:', title)
        
        # Save the title if we have a conversation ID
        if conversation_id:
            try:
                # Always use in-memory storage by default
                redis_conn = get_redis_connection()
                conversation_key = f"conversation:{conversation_id}"
                
                # Update in-memory storage
                if isinstance(redis_conn, FallbackDict):
                    conv_data = redis_conn.get(conversation_key, {})
                    conv_data['title'] = title
                    redis_conn[conversation_key] = conv_data
                
                # If Redis is available, also update there
                if redis_available():
                    try:
                        redis_conn_redis = get_redis_connection(force_redis=True)
                        if not isinstance(redis_conn_redis, FallbackDict):
                            redis_conn_redis.hset(conversation_key, "title", title)
                            redis_conn_redis.expire(conversation_key, REDIS_EXPIRE_SECONDS)
                    except Exception as e:
                        logger.warning(f"Failed to sync title to Redis: {e}")
                
            except Exception as e:
                logger.error(f"Error saving title for conversation {conversation_id}: {e}")
        
        return jsonify({"title": title or default_title})
    except Exception as e:
        logger.error(f"Unexpected error in api_title_summary: {e}")
        return jsonify({"title": "新会话"}), 200

@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        print('[FLASK] /api/chat received:', request.get_json())
        data = request.get_json()
        question = data.get("question", "").strip()
        selected_model = data.get("model", "grok-3-mini")
        history = data.get("history", [])
        conversation_id = data.get("conversation_id")

        # Always use in-memory storage by default
        redis_conn = get_redis_connection()
        
        # If Redis is available, we'll sync with it after updating in-memory
        redis_available_flag = redis_available()
        redis_conn_redis = None
        if redis_available_flag:
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}")
                redis_available_flag = False

        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            # If it's a new conversation, save it with a default title for now
            # The title will be updated later by /api/title_summary
            created_at = datetime.now().isoformat()
            conversation_data = {
                'id': conversation_id,
                'title': "New Chat",
                'created_at': created_at,
                'updated_at': created_at
            }
            
            # Save to in-memory storage
            if isinstance(redis_conn, FallbackDict):
                redis_conn[f"conversation:{conversation_id}"] = conversation_data
                # Initialize messages list
                redis_conn[f"messages:{conversation_id}"] = []
                # Add to conversations list
                conversations = redis_conn.get(CONVERSATIONS_KEY, [])
                if not isinstance(conversations, list):
                    conversations = []
                if conversation_id not in conversations:
                    conversations.append(conversation_id)
                    redis_conn[CONVERSATIONS_KEY] = conversations
            if not isinstance(conversations, list):
                conversations = []
            if conversation_id not in conversations:
                conversations.append(conversation_id)
                redis_conn[CONVERSATIONS_KEY] = conversations
            
            # If Redis is available, sync the new conversation
            if redis_available_flag and redis_conn_redis:
                try:
                    redis_conn_redis.hset(f"conversation:{conversation_id}", mapping=conversation_data)
                    redis_conn_redis.expire(f"conversation:{conversation_id}", REDIS_EXPIRE_SECONDS)
                    redis_conn_redis.lpush(CONVERSATIONS_KEY, conversation_id)
                    redis_conn_redis.expire(CONVERSATIONS_KEY, REDIS_EXPIRE_SECONDS)
                    messages_key = f"messages:{conversation_id}"
                    redis_conn_redis.rpush(messages_key, '')  # Add empty message to create the list
                    redis_conn_redis.expire(messages_key, REDIS_EXPIRE_SECONDS)
                except Exception as e:
                    logger.warning(f"Failed to sync new conversation to Redis: {e}")

        if not question:
            return jsonify({"error": "Please enter a question."}), 400

        # Save user message
        message_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        messages_key = f"messages:{conversation_id}"
        message_data = {
            'id': message_id,
            'conversation_id': conversation_id,
            'role': "user",
            'content': question,
            'timestamp': timestamp
        }

        # Save to in-memory storage if using FallbackDict
        if isinstance(redis_conn, FallbackDict):
            messages = redis_conn.get(messages_key, [])
            if messages == ['']:  # Handle the initial empty message
                messages = []
            messages.append(json.dumps(message_data))
            redis_conn[messages_key] = messages
            
            # Update conversation's updated_at in memory
            conv_data = redis_conn.get(f"conversation:{conversation_id}", {})
            if not isinstance(conv_data, dict):
                conv_data = {}
            conv_data['updated_at'] = timestamp
            redis_conn[f"conversation:{conversation_id}"] = conv_data
        
        # If Redis is available, sync the message and conversation update
        if redis_available_flag and redis_conn_redis:
            try:
                # Sync the message
                messages_key_redis = f"messages:{conversation_id}"
                redis_conn_redis.rpush(messages_key_redis, json.dumps(message_data))
                redis_conn_redis.expire(messages_key_redis, REDIS_EXPIRE_SECONDS)
                
                # Sync the conversation update
                redis_conn_redis.hset(f"conversation:{conversation_id}", "updated_at", timestamp)
                redis_conn_redis.expire(f"conversation:{conversation_id}", REDIS_EXPIRE_SECONDS)
            except Exception as e:
                logger.warning(f"Failed to sync message to Redis: {e}")
            # This block is redundant as we already synced to Redis above
            # The error was occurring because we were trying to use Redis commands on FallbackDict
            pass

        # Append user message to history for LLM processing
        history.append({"role": "user", "content": question})
        llm_messages = summarize_history(history, max_chars=2000)

        print(f"[api_chat] question={question!r}")
        print(f"[api_chat] model={selected_model!r}")
        print(f"[api_chat] history={history!r}")

        def generate():
            nonlocal llm_messages
            answer_chunks = get_llm_cached(selected_model, llm_messages, stream=True)
            full_answer = ''
            for chunk in answer_chunks:
                full_answer += chunk
                yield chunk
            
            # Save AI response
            message_id_ai = str(uuid.uuid4())
            timestamp_ai = datetime.now().isoformat()
            message_data_ai = {
                'id': message_id_ai,
                'conversation_id': conversation_id,
                'role': "assistant",
                'content': full_answer,
                'timestamp': timestamp_ai
            }
            
            if isinstance(redis_conn, FallbackDict):
                # In-memory storage
                messages = redis_conn.get(messages_key, [])
                messages.append(json.dumps(message_data_ai))
                redis_conn[messages_key] = messages
                
                # Update conversation's updated_at
                conv_data = redis_conn.get(f"conversation:{conversation_id}", {})
                conv_data['updated_at'] = timestamp_ai
                redis_conn[f"conversation:{conversation_id}"] = conv_data
            else:
                # Redis storage
                redis_conn.rpush(messages_key, json.dumps(message_data_ai))
                # Reset expiration for messages key on new message
                redis_conn.expire(messages_key, REDIS_EXPIRE_SECONDS)
                # Also reset expiration for conversation data
                redis_conn.expire(f"conversation:{conversation_id}", REDIS_EXPIRE_SECONDS)
                # Update conversation's updated_at
                redis_conn.hset(f"conversation:{conversation_id}", "updated_at", timestamp_ai)

        return Response(generate(), mimetype='text/plain')
        
    except Exception as e:
        logger.error(f"Error in api_chat: {e}")
        return jsonify({"error": "An error occurred while processing your request"}), 500

@app.route('/api/messages', methods=['POST'])
def add_message():
    try:
        data = request.get_json()
        conversation_id = data.get('conversation_id')
        role = data.get('role')
        content = data.get('content')
        
        if not all([conversation_id, role, content]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Always use in-memory storage by default
        redis_conn = get_redis_connection()
        
        # Check if Redis is available for syncing
        redis_available_flag = redis_available()
        redis_conn_redis = None
        if redis_available_flag:
            try:
                redis_conn_redis = get_redis_connection(force_redis=True)
            except Exception as e:
                logger.warning(f"Failed to connect to Redis for message addition: {e}")
                redis_available_flag = False
        
        message_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        message_data = {
            'id': message_id,
            'conversation_id': conversation_id,
            'role': role,
            'content': content,
            'timestamp': timestamp
        }
        
        messages_key = f'messages:{conversation_id}'
        
        # Save to in-memory storage
        if isinstance(redis_conn, FallbackDict):
            messages = redis_conn.get(messages_key, [])
            if messages == ['']:  # Handle the initial empty message
                messages = []
            messages.append(json.dumps(message_data))
            redis_conn[messages_key] = messages
            
            # Update conversation's updated_at in memory
            conv_data = redis_conn.get(f'conversation:{conversation_id}', {})
            conv_data['updated_at'] = timestamp
            redis_conn[f'conversation:{conversation_id}'] = conv_data
        
        # If Redis is available, sync the message and conversation update
        if redis_available_flag and redis_conn_redis:
            try:
                # Sync the message
                redis_conn_redis.rpush(messages_key, json.dumps(message_data))
                redis_conn_redis.expire(messages_key, REDIS_EXPIRE_SECONDS)
                
                # Sync the conversation update
                redis_conn_redis.hset(f'conversation:{conversation_id}', 'updated_at', timestamp)
                redis_conn_redis.expire(f'conversation:{conversation_id}', REDIS_EXPIRE_SECONDS)
            except Exception as e:
                logger.warning(f"Failed to sync message to Redis: {e}")
        
        return jsonify({
            'id': message_id,
            'conversation_id': conversation_id,
            'role': role,
            'content': content,
            'timestamp': timestamp
        }), 201
        
    except Exception as e:
        logger.error(f'Error adding message: {e}')
        return jsonify({'error': str(e)}), 500

def get_llm_cache_key(model, messages):
    # 用模型+消息内容哈希做key
    key_src = model + json.dumps(messages, ensure_ascii=False)
    return hashlib.md5(key_src.encode('utf-8')).hexdigest()

def get_llm_cached(model, messages, stream=False):
    # 临时禁用缓存，强制每次都请求 LLM
    if stream:
        chunks = []
        for chunk in ask_grok_stream(model, messages):
            chunks.append(chunk)
            yield chunk
    else:
        return ask_grok(model, messages)

# 自动摘要历史，超 max_chars 时用 LLM 总结前面的，仅保留最近3条原文
# 实际生产建议用 LLM 生成摘要，这里用拼接模拟

def summarize_history(history, max_chars=4000, keep_last_n=8, summary_max_len=1000):
    # 移除已有 system 摘要
    filtered = [msg for msg in history if msg.get('role') != 'system']
    total_chars = sum(len(msg.get('content', '')) for msg in filtered)
    if total_chars <= max_chars:
        return filtered
    # 保留最近N条，前面合并成摘要
    recent = filtered[-keep_last_n:]
    to_summarize = filtered[:-keep_last_n]
    if not to_summarize:
        return recent
    summary_prompt = (
        f"请用简明但尽量保留细节的方式总结以下多轮对话内容，摘要长度不超过{summary_max_len}字，便于后续上下文继续：\n"
        + '\n'.join(f"[{msg['role']}]: {msg['content']}" for msg in to_summarize)
    )
    summary_text = get_llm_cached('grok-3-mini', [{"role": "user", "content": summary_prompt}])
    summary = {'role': 'system', 'content': f'历史摘要：{summary_text}'}
    new_history = [summary] + recent
    # 如果还超长，递归摘要
    if sum(len(msg.get('content', '')) for msg in new_history) > max_chars:
        return summarize_history(new_history, max_chars, keep_last_n, summary_max_len)
    return new_history

# Function to query Grok model
def ask_grok_stream(model, messages):
    try:
        logger.info(f"[ask_grok_stream] Starting streaming request with model: {model}")
        logger.debug(f"[ask_grok_stream] Messages: {json.dumps(messages, indent=2, ensure_ascii=False)}")
        
        # Validate model name
        if not model or not isinstance(model, str):
            error_msg = f"Invalid model name: {model}"
            logger.error(error_msg)
            yield f"Error: {error_msg}"
            return
            
        # Validate messages format
        if not messages or not isinstance(messages, list):
            error_msg = f"Invalid messages format: {messages}"
            logger.error(error_msg)
            yield f"Error: {error_msg}"
            return
            
        for msg in messages:
            if not isinstance(msg, dict) or 'role' not in msg or 'content' not in msg:
                error_msg = f"Invalid message format in: {msg}"
                logger.error(error_msg)
                yield f"Error: {error_msg}"
                return
        
        # Check if client is properly initialized
        if not hasattr(client, 'chat') or not hasattr(client.chat.completions, 'create'):
            error_msg = "OpenAI client is not properly initialized"
            logger.error(error_msg)
            yield f"Error: {error_msg}"
            return
        
        try:
            # Make the streaming API request
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=2000
            )
            
            # Stream the response chunks
            for chunk in response:
                if (hasattr(chunk, 'choices') and 
                    len(chunk.choices) > 0 and 
                    hasattr(chunk.choices[0], 'delta') and
                    hasattr(chunk.choices[0].delta, 'content') and 
                    chunk.choices[0].delta.content is not None):
                    content = chunk.choices[0].delta.content
                    yield content
                
        except Exception as e:
            error_msg = f"Error during streaming: {type(e).__name__} - {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield f"\n\nError: {error_msg}"
            
    except openai.APIError as e:
        error_msg = f"OpenAI API Error: {type(e).__name__} - {str(e)}"
        logger.error(error_msg, exc_info=True)
        yield f"\n\nAPI Error: {error_msg}"
    except Exception as e:
        error_msg = f"Unexpected error: {type(e).__name__} - {str(e)}"
        logger.error(error_msg, exc_info=True)
        yield f"\n\nError: {error_msg}"

# 兼容非流式（表单POST）
def ask_grok(model, messages):
    try:
        logger.info(f"[ask_grok] Starting request with model: {model}")
        logger.debug(f"[ask_grok] Messages: {json.dumps(messages, indent=2, ensure_ascii=False)}")
        
        # Validate model name
        if not model or not isinstance(model, str):
            error_msg = f"Invalid model name: {model}"
            logger.error(error_msg)
            return f"Error: {error_msg}"
            
        # Validate messages format
        if not messages or not isinstance(messages, list):
            error_msg = f"Invalid messages format: {messages}"
            logger.error(error_msg)
            return f"Error: {error_msg}"
            
        for msg in messages:
            if not isinstance(msg, dict) or 'role' not in msg or 'content' not in msg:
                error_msg = f"Invalid message format in: {msg}"
                logger.error(error_msg)
                return f"Error: {error_msg}"
        
        # Make the API request
        start_time = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=2000
        )
        
        duration = time.time() - start_time
        logger.info(f"[ask_grok] Request completed in {duration:.2f}s")
        
        if not response.choices or not response.choices[0].message:
            error_msg = "Empty or invalid response from API"
            logger.error(f"{error_msg}: {response}")
            return f"Error: {error_msg}"
            
        return response.choices[0].message.content
        
    except openai.APIError as e:
        error_msg = f"OpenAI API Error: {type(e).__name__} - {str(e)}"
        logger.error(error_msg, exc_info=True)
        return f"API Error: {error_msg}"
    except Exception as e:
        error_msg = f"Unexpected error: {type(e).__name__} - {str(e)}"
        logger.error(error_msg, exc_info=True)
        return f"Error: {error_msg}"

# Database configuration
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, socket_connect_timeout=1, socket_keepalive=True)
    redis_client.ping()
    logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT} successfully")
    REDIS_AVAILABLE = True
except (redis.ConnectionError, redis.TimeoutError) as e:
    REDIS_AVAILABLE = False
    logger.warning(f"Could not connect to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}. Using in-memory fallback storage.")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))  # Default to 5001 if PORT not set
    app.run(host='0.0.0.0', port=port, debug=True)
