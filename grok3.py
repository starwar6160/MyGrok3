import openai
import os
import hashlib
import json
from flask import Flask, render_template, request, Response, stream_with_context, send_from_directory, jsonify
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta
import uuid
import time

# Define the data directory
DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
CONVERSATIONS_DIR = os.path.join(DATA_DIR, 'conversations')
os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

# === React 静态页面托管 ===
app = Flask(__name__, static_folder="frontend/build", template_folder="frontend/build")

# 允许跨域
try:
    from flask_cors import CORS
    CORS(app)
except ImportError:
    pass  # 如果没装CORS，先不报错

# Configure the xAI API client
api_key = os.getenv("XAI_API_KEY")
if not api_key:
    raise ValueError("XAI_API_KEY environment variable not set")

client = openai.OpenAI(
    base_url="https://api.x.ai/v1",
    api_key=api_key
)

# 简单 LLM cache（可换成 Redis 等）
llm_cache = {}

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
import os

def ensure_db_dir_exists(db_path):
    dir_name = os.path.dirname(db_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)

DATABASE = os.getenv('SQLITE_DATABASE')
if not DATABASE:
    # Default: local file for dev, or /data/chat_topics.db for Docker if /data exists
    if os.path.isdir('/data'):
        DATABASE = '/data/chat_topics.db'
    else:
        DATABASE = 'chat_topics.db'

ensure_db_dir_exists(DATABASE)

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def save_conversation_to_file(conversation_id, messages):
    """Saves the conversation messages to a text file."""
    file_path = os.path.join(CONVERSATIONS_DIR, f"{conversation_id}.txt")
    with open(file_path, 'w', encoding='utf-8') as f:
        for message in messages:
            f.write(f"{message['role']}: {message['content']}\n")

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL,
                last_file_update TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS code_snippets (
                id TEXT PRIMARY KEY,
                title TEXT,
                code TEXT,
                language TEXT,
                created_at TEXT,
                conversation_id TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id)
            )
        ''')
        conn.commit()

# Initialize the database on app startup
with app.app_context():
    init_db()

def save_code_snippet(title, code, language='python', conversation_id=None):
    snippet_id = str(uuid.uuid4())
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO code_snippets (id, title, code, language, created_at, conversation_id) VALUES (?, ?, ?, ?, ?, ?)",
            (snippet_id, title, code, language, created_at, conversation_id)
        )
        conn.commit()
    return snippet_id

def save_conversation(conversation_id, title):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO conversations (id, title) VALUES (?, ?)", (conversation_id, title))
        conn.commit()

def update_conversation_timestamp(conversation_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE conversations SET last_active = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))
        conn.commit()

def get_messages_for_conversation(conversation_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY timestamp", (conversation_id,))
        return [dict(row) for row in cursor.fetchall()]

def save_message(conversation_id, role, content):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
                       (conversation_id, role, content))
        conn.commit()

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    build_dir = Path(app.static_folder)
    file_path = build_dir / path
    if path != "" and file_path.exists():
        return send_from_directory(build_dir, path)
    else:
        return send_from_directory(build_dir, "index.html")

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
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
            conn.commit()
    return jsonify({"title": title or "新会话"})

def get_conversations(active_within_hours=None, older_than_hours=None):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT id, title, created_at, last_active FROM conversations"
        conditions = []
        params = []

        if active_within_hours is not None:
            active_time_threshold = datetime.now() - timedelta(hours=active_within_hours)
            conditions.append("last_active >= ?")
            params.append(active_time_threshold.strftime('%Y-%m-%d %H:%M:%S'))

        if older_than_hours is not None:
            older_time_threshold = datetime.now() - timedelta(hours=older_than_hours)
            conditions.append("last_active < ?")
            params.append(older_time_threshold.strftime('%Y-%m-%d %H:%M:%S'))
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY last_active DESC"
        
        cursor.execute(query, params)
        conversations = []
        for row in cursor.fetchall():
            conv = dict(row)
            conv['messages'] = get_messages_for_conversation(conv['id'])
            conversations.append(conv)
        return conversations

def get_messages_for_conversation(conversation_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC", (conversation_id,))
        return [dict(row) for row in cursor.fetchall()]

@app.route("/api/conversations", methods=["GET"])
def api_conversations():
    conv_type = request.args.get('type', 'active') # 'active' or 'history'

    if conv_type == 'active':
        # Return conversations active in the last 24 hours
        conversations = get_conversations(active_within_hours=24)
    elif conv_type == 'history':
        # Return conversations older than 24 hours
        conversations = get_conversations(older_than_hours=24)
    else:
        # Default to all if no type specified or invalid type
        conversations = get_conversations()

    return jsonify(conversations)

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
        save_conversation(conversation_id, "New Chat")

    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    # Save user message
    save_message(conversation_id, "user", question)

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
        save_message(conversation_id, "assistant", full_answer)
        update_conversation_timestamp(conversation_id)



    return Response(generate(), mimetype='text/plain')

@app.route("/api/backup_db", methods=["POST"])
def backup_database():
    try:
        backup_dir = os.path.join(DATA_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"database_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}.db")

        source_conn = sqlite3.connect(DATABASE)
        backup_conn = sqlite3.connect(backup_path)
        with backup_conn:
            source_conn.backup(backup_conn)
        source_conn.close()
        backup_conn.close()
        return jsonify({"message": f"Database backed up successfully to {backup_path}"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to backup database: {str(e)}"}), 500

import socket

def find_free_port(start_port=5000, max_tries=10):
    port = start_port
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('0.0.0.0', port)) != 0:
                return port
            port += 1
    raise RuntimeError("No free port found in range.")

# Function to run in a background thread for periodic file updates
def background_file_updater():
    while True:
        with app.app_context():
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Select conversations that haven't been updated in the last 5 minutes
                # and whose last_active is more recent than last_file_update
                cursor.execute("""
                    SELECT id, last_active, last_file_update FROM conversations
                    WHERE last_active < ? AND last_active > last_file_update
                """, (datetime.now() - timedelta(minutes=5),))
                conversations_to_update = cursor.fetchall()

                for conv in conversations_to_update:
                    conversation_id = conv['id']
                    print(f"Updating file for conversation: {conversation_id}")
                    all_messages = get_messages_for_conversation(conversation_id)
                    save_conversation_to_file(conversation_id, all_messages)
                    # Update last_file_update timestamp in DB
                    cursor.execute("UPDATE conversations SET last_file_update = ? WHERE id = ?",
                                   (datetime.now(), conversation_id))
                conn.commit()
        time.sleep(30) # Check every 30 seconds

# Start the background thread when the application starts
@app.before_first_request
def start_background_updater():
    thread = threading.Thread(target=background_file_updater)
    thread.daemon = True # Allow the main program to exit even if the thread is running
    thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
