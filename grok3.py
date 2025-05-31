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
CONVERSATIONS_TITLE_KEY = "conversation_titles"

# LLM 缓存函数
def get_llm_cache(prompt_hash):
    response = redis_client.get(f"llm_cache:{prompt_hash}")
    if response:
        return response.decode('utf-8')
    return None

def set_llm_cache(prompt_hash, response):
    redis_client.set(f"llm_cache:{prompt_hash}", response)
    # Set expiration for cache entries (e.g., 7 days)
    redis_client.expire(f"llm_cache:{prompt_hash}", timedelta(days=7))


@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    conversation_ids = redis_client.lrange(CONVERSATIONS_KEY, 0, -1)
    conversations_list = []
    for conv_id_bytes in conversation_ids:
        conv_id = conv_id_bytes.decode('utf-8')
        conv_data = redis_client.hgetall(f"conversation:{conv_id}")
        if conv_data:
            title = conv_data.get(b'title', b'').decode('utf-8')
            created_at = conv_data.get(b'created_at', b'').decode('utf-8')
            # Get the last message for the conversation
            messages = redis_client.lrange(f"messages:{conv_id}", -1, -1)
            last_message_content = ""
            if messages:
                last_message = json.loads(messages[0].decode('utf-8'))
                last_message_content = last_message.get('content', '')

            conversations_list.append({
                'id': conv_id,
                'title': title,
                'created_at': created_at,
                'last_message': last_message_content
            })
    # Sort by created_at in descending order
    conversations_list.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(conversations_list)

@app.route('/api/conversations', methods=['POST'])
def create_conversation():
    data = request.get_json()
    title = data.get('title', 'New Conversation')
    conversation_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()

    # Store conversation metadata in a hash
    redis_client.hset(f"conversation:{conversation_id}", mapping={
        'id': conversation_id,
        'title': title,
        'created_at': created_at
    })
    # Add conversation ID to a list for ordering
    redis_client.lpush(CONVERSATIONS_KEY, conversation_id)
    return jsonify({'id': conversation_id, 'title': title, 'created_at': created_at}), 201

@app.route('/api/conversations/<conversation_id>', methods=['GET'])
def get_conversation_messages(conversation_id):
    messages_data = redis_client.lrange(f"messages:{conversation_id}", 0, -1)
    messages_list = []
    for msg_bytes in messages_data:
        messages_list.append(json.loads(msg_bytes.decode('utf-8')))
    return jsonify(messages_list)

@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    # Delete messages associated with the conversation
    redis_client.delete(f"messages:{conversation_id}")
    # Delete conversation metadata
    redis_client.delete(f"conversation:{conversation_id}")
    # Remove conversation ID from the list
    redis_client.lrem(CONVERSATIONS_KEY, 0, conversation_id)
    return jsonify({'message': 'Conversation deleted'}), 200

@app.route('/api/messages', methods=['POST'])
def add_message():
    data = request.get_json()
    conversation_id = data.get('conversation_id')
    role = data.get('role')
    content = data.get('content')
    message_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()

    message_data = {
        'id': message_id,
        'conversation_id': conversation_id,
        'role': role,
        'content': content,
        'timestamp': timestamp
    }
    # Store message in a list associated with the conversation
    redis_client.rpush(f"messages:{conversation_id}", json.dumps(message_data))
    return jsonify(message_data), 201

@app.route('/api/llm_cache/<prompt_hash>', methods=['GET'])
def get_llm_cache_api(prompt_hash):
    response = get_llm_cache(prompt_hash)
    if response:
        return jsonify({'response': response}), 200
    return jsonify({'message': 'Cache not found'}), 404

@app.route('/api/llm_cache', methods=['POST'])
def set_llm_cache_api():
    data = request.get_json()
    prompt_hash = data.get('hash')
    response_content = data.get('response')
    if prompt_hash and response_content:
        set_llm_cache(prompt_hash, response_content)
        return jsonify({'message': 'Cache set successfully'}), 201
    return jsonify({'message': 'Invalid data'}), 400

@app.route("/api/title_summary", methods=["POST"])
def api_title_summary():
    data = request.get_json()
    print('[FLASK] /api/title_summary received:', data)
    messages = data.get("messages", [])
    conversation_id = data.get("conversation_id")
    prompt = (
        "请根据以下对话内容，自动归纳一个简明、概括性的标题（10字以内），只返回标题本身，不要加任何解释：\n"
        + '\n'.join(f"[{m.get('role','')}] {m.get('content','')}" for m in messages)
    )
    title = ask_grok("grok-3-mini", [{"role": "user", "content": prompt}])
    # 只取前10字，去除空白
    title = (title or "新会话").strip().replace("\n", "").replace("：", ":")[:10]
    print('[FLASK] /api/title_summary response:', title)
    if conversation_id:
        redis_client.hset(f"conversation:{conversation_id}", "title", title)
    return jsonify({"title": title or "新会话"})

@app.route("/api/chat", methods=["POST"])
def api_chat():
    print('[FLASK] /api/chat received:', request.get_json())
    data = request.get_json()
    question = data.get("question", "").strip()
    selected_model = data.get("model", "grok-3-mini")
    history = data.get("history", [])
    conversation_id = data.get("conversation_id")

    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        # If it's a new conversation, save it with a default title for now
        # The title will be updated later by /api/title_summary
        created_at = datetime.now().isoformat()
        redis_client.hset(f"conversation:{conversation_id}", mapping={
            'id': conversation_id,
            'title': "New Chat",
            'created_at': created_at
        })
        redis_client.lpush(CONVERSATIONS_KEY, conversation_id)

    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    # Save user message
    message_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    message_data = {
        'id': message_id,
        'conversation_id': conversation_id,
        'role': "user",
        'content': question,
        'timestamp': timestamp
    }
    redis_client.rpush(f"messages:{conversation_id}", json.dumps(message_data))

    # Append user message to history for LLM processing
    history.append({"role": "user", "content": question})
    messages = summarize_history(history, max_chars=2000)

    print(f"[api_chat] question={question!r}")
    print(f"[api_chat] model={selected_model!r}")
    print(f"[api_chat] history={history!r}")

    def generate():
        answer_chunks = get_llm_cached(selected_model, messages, stream=True)
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
        redis_client.rpush(f"messages:{conversation_id}", json.dumps(message_data_ai))

    return Response(generate(), mimetype='text/plain')

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))  # Default to 5001 if PORT not set
    app.run(host='0.0.0.0', port=port, debug=True)
