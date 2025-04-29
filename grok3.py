import openai
import os
import hashlib
import json
import sqlite3
import openai
import os
import hashlib
from flask import Flask, render_template, request, Response, stream_with_context, send_from_directory, jsonify
from pathlib import Path

# === React 静态页面托管 ===
app = Flask(__name__, static_folder="frontend/build", template_folder="frontend/build")

# 允许跨域
try:
    from flask_cors import CORS
    CORS(app)
except ImportError:
    pass  # 如果没装CORS，先不报错

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    build_dir = Path(app.static_folder)
    file_path = build_dir / path
    if path != "" and file_path.exists():
        return send_from_directory(build_dir, path)
    else:
        return send_from_directory(build_dir, "index.html")

# === SQLite 持久化设置 ===
DB_PATH = 'chat_history.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        role TEXT,
        content TEXT,
        conversation_id TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

def save_message_to_db(timestamp, role, content, conversation_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO chat_messages (timestamp, role, content, conversation_id) VALUES (?, ?, ?, ?)''',
              (timestamp, role, content, conversation_id))
    conn.commit()
    conn.close()

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
        save_message_to_db(int(time.time()*1000), 'user', question, conversation_id)
        def stream_gen():
            assistant_content = ""
            for chunk in get_llm_cached(selected_model, messages, stream=True):
                assistant_content += chunk
                yield chunk
            # --- 保存AI回复 ---
            save_message_to_db(int(time.time()*1000), 'assistant', assistant_content, conversation_id)
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
    prompt = (
        "请根据以下对话内容，自动归纳一个简明、概括性的标题（10字以内），只返回标题本身，不要加任何解释：\n"
        + '\n'.join(f"[{m.get('role','')}] {m.get('content','')}" for m in messages)
    )
    title = ask_grok("grok-3-mini", [{"role": "user", "content": prompt}])
    # 只取前10字，去除空白
    title = (title or "新会话").strip().replace("\n", "").replace("：", ":")[:10]
    print('[FLASK] /api/title_summary response:', title)
    return jsonify({"title": title or "新会话"})

@app.route("/api/chat", methods=["POST"])
def api_chat():
    print('[FLASK] /api/chat received:', request.get_json())
    data = request.get_json()
    question = data.get("question", "").strip()
    selected_model = data.get("model", "grok-3-mini")
    history = data.get("history", [])
    conversation_id = data.get("conversation_id") or "default"
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
    # 拼接历史+当前
    history.append({"role": "user", "content": question})
    messages = summarize_history(history, max_chars=2000)
    # 保存用户消息
    import time
    save_message_to_db(int(time.time()*1000), 'user', question, conversation_id)
    print(f"[api_chat] question={question!r}")
    print(f"[api_chat] model={selected_model!r}")
    print(f"[api_chat] history={history!r}")
    def generate():
        import types
        answer_chunks = get_llm_cached(selected_model, messages, stream=True)
        import sys
        full_answer = ''
        for chunk in answer_chunks:
            full_answer += chunk
            yield chunk
        # 保存AI回复（只保存一次完整内容）
        save_message_to_db(int(time.time()*1000), 'assistant', full_answer, conversation_id)
    return Response(generate(), mimetype='text/plain')

import socket

def find_free_port(start_port=5000, max_tries=10):
    port = start_port
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('0.0.0.0', port)) != 0:
                return port
            port += 1
    raise RuntimeError("No free port found in range.")

if __name__ == "__main__":
    try:
        port = find_free_port(5000, 11)
        print(f" * Flask running on port {port}")
        app.run(debug=True, host="0.0.0.0", port=port)
    except Exception as e:
        print(f"启动失败: {e}")
