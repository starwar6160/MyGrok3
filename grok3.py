import openai
import os
import hashlib
from flask import Flask, render_template, request, Response, stream_with_context
import json
import sqlite3

# Initialize Flask app
app = Flask(__name__)

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
    key = get_llm_cache_key(model, messages)
    if key in llm_cache:
        result = llm_cache[key]
        if stream:
            # 若缓存为字符串，模拟流式返回
            for i in range(0, len(result), 50):
                yield result[i:i+50]
            return
        else:
            return result
    # 未命中缓存，调用 LLM
    if stream:
        chunks = []
        for chunk in ask_grok_stream(model, messages):
            chunks.append(chunk)
            yield chunk
        llm_cache[key] = ''.join(chunks)
    else:
        result = ask_grok(model, messages)
        llm_cache[key] = result
        return result

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
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content
    except openai.NotFoundError as e:
        return f"API Error: {e}"
    except Exception as e:
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
    return render_template(
        "index.html",
        answer=answer,
        error=error,
        question=question,
        selected_model=selected_model
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
