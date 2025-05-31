import openai
import os
import hashlib
import json
from flask import Flask, render_template, request, Response, stream_with_context, send_from_directory, jsonify
from pathlib import Path
import redis
from datetime import datetime, timedelta
import uuid
import time
import threading
import logging
from functools import wraps

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global flag to track Redis availability
REDIS_AVAILABLE = True

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

# Initialize in-memory fallback storage
fallback_storage = FallbackDict()

def redis_available():
    """Check if Redis is available"""
    global REDIS_AVAILABLE
    if not REDIS_AVAILABLE:
        return False
    
    try:
        r = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=1)
        r.ping()
        return True
    except (redis.ConnectionError, redis.TimeoutError):
        REDIS_AVAILABLE = False
        logger.warning("Redis connection failed. Falling back to in-memory storage.")
        return False

def get_redis_connection():
    """Get Redis connection or fallback to in-memory storage"""
    if redis_available():
        try:
            return redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=1)
        except (redis.ConnectionError, redis.TimeoutError):
            global REDIS_AVAILABLE
            REDIS_AVAILABLE = False
            logger.warning("Redis connection failed. Falling back to in-memory storage.")
    return fallback_storage

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

# Configure the xAI API client
api_key = os.getenv("XAI_API_KEY")
if not api_key:
    raise ValueError("XAI_API_KEY environment variable not set")

client = openai.OpenAI(
    base_url="https://api.x.ai/v1",
    api_key=api_key
)

# 简单 LLM cache（可换成 Redis 等）
redis_client = redis.Redis(host='localhost', port=6379, db=0)

# Redis keys for conversations and messages
CONVERSATIONS_KEY = "conversations"
# Expiration time in seconds (7 days)
REDIS_EXPIRE_SECONDS = 7 * 24 * 60 * 60  # 7 days in seconds

# LLM 缓存函数
def get_llm_cache(prompt_hash):
    try:
        return get_redis_connection().get(f'llm_cache:{prompt_hash}')
    except Exception as e:
        logger.error(f"Error getting LLM cache: {e}")
        return None

def set_llm_cache(prompt_hash, response):
    try:
        get_redis_connection().setex(f'llm_cache:{prompt_hash}', timedelta(days=7), response)
    except Exception as e:
        logger.error(f"Error setting LLM cache: {e}")

@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    try:
        redis_conn = get_redis_connection()
        if isinstance(redis_conn, FallbackDict):
            # For in-memory storage, we need to handle keys differently
            conversations = []
            for key, value in redis_conn.items():
                if key.startswith('conversation:'):
                    conv_data = value if isinstance(value, dict) else {}
                    conversations.append({
                        'id': key.split(':')[1],
                        'title': conv_data.get('title', 'Untitled'),
                        'created_at': conv_data.get('created_at', ''),
                        'updated_at': conv_data.get('updated_at', '')
                    })
            return jsonify(conversations)
        else:
            # Original Redis implementation
            conv_ids = redis_conn.keys('conversation:*')
            conversations = []
            for conv_id in conv_ids:
                conv_data = redis_conn.hgetall(conv_id)
                if conv_data:
                    conv_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in conv_data.items()}
                    conversations.append({
                        'id': conv_id.decode('utf-8').split(':')[1],
                        'title': conv_data.get('title', 'Untitled'),
                        'created_at': conv_data.get('created_at', ''),
                        'updated_at': conv_data.get('updated_at', '')
                    })
            return jsonify(conversations)
    except Exception as e:
        logger.error(f"Error getting conversations: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversations', methods=['POST'])
def create_conversation():
    try:
        redis_conn = get_redis_connection()
        conversation_id = str(uuid.uuid4())
        title = "New Conversation"
        created_at = datetime.now().isoformat()
        
        conversation_data = {
            'id': conversation_id,
            'title': title,
            'created_at': created_at,
            'updated_at': created_at
        }
        
        if isinstance(redis_conn, FallbackDict):
            # In-memory storage
            redis_conn[f'conversation:{conversation_id}'] = conversation_data
            # Create empty messages list
            redis_conn[f'messages:{conversation_id}'] = []
        else:
            # Redis storage
            redis_conn.hset(f'conversation:{conversation_id}', mapping={
                'id': conversation_id,
                'title': title,
                'created_at': created_at,
                'updated_at': created_at
            })
            redis_conn.expire(f'conversation:{conversation_id}', REDIS_EXPIRE_SECONDS)
            # Create empty messages list
            redis_conn.rpush(f'messages:{conversation_id}', '')
            redis_conn.expire(f'messages:{conversation_id}', REDIS_EXPIRE_SECONDS)
        
        return jsonify({
            'id': conversation_id, 
            'title': title,
            'created_at': created_at,
            'messages': []
        })
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        return jsonify({'error': 'Failed to create conversation'}), 500

@app.route('/api/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Get conversation metadata"""
    try:
        redis_conn = get_redis_connection()
        
        if isinstance(redis_conn, FallbackDict):
            # In-memory storage
            conv_data = redis_conn.get(f'conversation:{conversation_id}', {})
            if not conv_data:
                return jsonify({'error': 'Conversation not found'}), 404
                
            title = conv_data.get('title', 'New Conversation')
            created_at = conv_data.get('created_at', datetime.now().isoformat())
        else:
            # Redis storage
            conv_data = redis_conn.hgetall(f'conversation:{conversation_id}')
            if not conv_data:
                return jsonify({'error': 'Conversation not found'}), 404
                
            title = conv_data.get(b'title', b'New Conversation').decode('utf-8')
            created_at = conv_data.get(b'created_at', datetime.now().isoformat().encode('utf-8')).decode('utf-8')
        
        return jsonify({
            'id': conversation_id,
            'title': title,
            'created_at': created_at,
            'messages': []  # Messages are loaded separately
        })
    except Exception as e:
        logger.error(f"Error getting conversation {conversation_id}: {e}")
        return jsonify({'error': 'Failed to retrieve conversation'}), 500

@app.route('/api/conversations/<conversation_id>/messages', methods=['GET'])
def get_conversation_messages_list(conversation_id):
    """Get all messages for a specific conversation"""
    try:
        redis_conn = get_redis_connection()
        messages = []
        
        if isinstance(redis_conn, FallbackDict):
            # In-memory storage
            message_list = redis_conn.get(f'messages:{conversation_id}', [])
            if not isinstance(message_list, list):
                if message_list == '':  # Handle empty string case
                    message_list = []
                else:
                    message_list = [message_list] if message_list else []
        else:
            # Redis storage
            message_list = redis_conn.lrange(f'messages:{conversation_id}', 0, -1)
        
        for msg in message_list:
            try:
                if isinstance(redis_conn, FallbackDict):
                    # In in-memory mode, messages are already stored as dictionaries or JSON strings
                    if isinstance(msg, str):
                        msg = json.loads(msg)
                else:
                    # In Redis mode, messages are stored as JSON strings
                    msg = json.loads(msg.decode('utf-8'))
                
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
        return jsonify({'error': 'Failed to retrieve messages'}), 500

@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    try:
        redis_conn = get_redis_connection()
        
        if isinstance(redis_conn, FallbackDict):
            # In-memory storage
            if f'conversation:{conversation_id}' in redis_conn:
                del redis_conn[f'conversation:{conversation_id}']
            if f'messages:{conversation_id}' in redis_conn:
                del redis_conn[f'messages:{conversation_id}']
        else:
            # Redis storage
            redis_conn.delete(f'conversation:{conversation_id}')
            redis_conn.delete(f'messages:{conversation_id}')
            # Remove from conversations list
            redis_conn.lrem('conversations', 0, conversation_id)
        
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        return jsonify({'error': 'Failed to delete conversation'}), 500

@app.route('/api/messages', methods=['POST'])
def add_message():
    try:
        data = request.get_json()
        conversation_id = data.get('conversation_id')
        role = data.get('role')
        content = data.get('content')
        
        if not all([conversation_id, role, content]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        message = {
            'id': str(uuid.uuid4()),
            'conversation_id': conversation_id,
            'role': role,
            'content': content,
            'created_at': datetime.now().isoformat()
        }
        
        redis_conn = get_redis_connection()
        message_json = json.dumps(message)
        updated_at = datetime.now().isoformat()
        
        if isinstance(redis_conn, FallbackDict):
            # In-memory storage
            # Get or create messages list
            messages_key = f'messages:{conversation_id}'
            messages = redis_conn.get(messages_key, [])
            if not isinstance(messages, list):
                messages = []
            messages.append(message)
            redis_conn[messages_key] = messages
            
            # Update conversation's updated_at
            conv_key = f'conversation:{conversation_id}'
            conv_data = redis_conn.get(conv_key, {})
            conv_data['updated_at'] = updated_at
            
            # If this is the first message, update the conversation title
            if role == 'user' and len(messages) <= 2:  # First user message (after system message)
                title = content[:50]  # Default to first 50 chars
                if len(content) > 50:
                    title += '...'
                conv_data['title'] = title
            
            redis_conn[conv_key] = conv_data
            
        if response:
            if isinstance(response, bytes):
                response = response.decode('utf-8')
            return jsonify({'response': response}), 200
        return jsonify({'message': 'Cache not found'}), 404
    except Exception as e:
        logger.error(f"Error getting LLM cache: {e}")
        return jsonify({'error': 'Failed to get cache'}), 500

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
                redis_conn = get_redis_connection()
                conversation_key = f"conversation:{conversation_id}"
                
                if isinstance(redis_conn, FallbackDict):
                    # In-memory storage
                    conv_data = redis_conn.get(conversation_key, {})
                    conv_data['title'] = title
                    redis_conn[conversation_key] = conv_data
                else:
                    # Redis storage
                    redis_conn.hset(conversation_key, "title", title)
                    redis_conn.expire(conversation_key, REDIS_EXPIRE_SECONDS)
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

        redis_conn = get_redis_connection()

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
            
            if isinstance(redis_conn, FallbackDict):
                # In-memory storage
                redis_conn[f"conversation:{conversation_id}"] = conversation_data
                # Initialize messages list
                redis_conn[f"messages:{conversation_id}"] = []
                # Add to conversations list
                conversations = redis_conn.get(CONVERSATIONS_KEY, [])
                conversations.append(conversation_id)
                redis_conn[CONVERSATIONS_KEY] = conversations
            else:
                # Redis storage
                redis_conn.hset(f"conversation:{conversation_id}", mapping=conversation_data)
                redis_conn.expire(f"conversation:{conversation_id}", REDIS_EXPIRE_SECONDS)
                redis_conn.lpush(CONVERSATIONS_KEY, conversation_id)
                redis_conn.expire(CONVERSATIONS_KEY, REDIS_EXPIRE_SECONDS)
                messages_key = f"messages:{conversation_id}"
                redis_conn.rpush(messages_key, '')  # Add empty message to create the list
                redis_conn.expire(messages_key, REDIS_EXPIRE_SECONDS)

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

        if isinstance(redis_conn, FallbackDict):
            # In-memory storage
            messages = redis_conn.get(messages_key, [])
            if messages == ['']:  # Handle the initial empty message
                messages = []
            messages.append(json.dumps(message_data))
            redis_conn[messages_key] = messages
            
            # Update conversation's updated_at
            conv_data = redis_conn.get(f"conversation:{conversation_id}", {})
            conv_data['updated_at'] = timestamp
            redis_conn[f"conversation:{conversation_id}"] = conv_data
        else:
            # Redis storage
            redis_conn.rpush(messages_key, json.dumps(message_data))
            # Reset expiration for messages key on new message
            redis_conn.expire(messages_key, REDIS_EXPIRE_SECONDS)
            # Also reset expiration for conversation data
            redis_conn.expire(f"conversation:{conversation_id}", REDIS_EXPIRE_SECONDS)
            # Update conversation's updated_at
            redis_conn.hset(f"conversation:{conversation_id}", "updated_at", timestamp)

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
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True
        )
        for chunk in response:
            if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except openai.NotFoundError as e:
        yield f"API Error: {e}"
    except Exception as e:
        yield f"Unexpected Error: {e}"

# 兼容非流式（表单POST）
def ask_grok(model, messages):
    try:
        print(f"[ask_grok] model={model!r}, messages={messages!r}")
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )
        print(f"[ask_grok] response={response}")
        return response.choices[0].message.content
    except openai.NotFoundError as e:
        print(f"[ask_grok] NotFoundError: {e}")
        return f"API Error: {e}"
    except Exception as e:
        print(f"[ask_grok] Exception: {e}")
        return f"Unexpected Error: {e}"

# Database configuration
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=1)
    redis_client.ping()
    logger.info("Connected to Redis successfully")
    REDIS_AVAILABLE = True
except (redis.ConnectionError, redis.TimeoutError) as e:
    REDIS_AVAILABLE = False
    logger.warning(f"Could not connect to Redis: {e}. Using in-memory fallback storage.")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))  # Default to 5001 if PORT not set
    app.run(host='0.0.0.0', port=port, debug=True)
