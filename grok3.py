import openai
import os
import hashlib
import json
import tiktoken
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

# Configure the OpenRouter API client
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=openai_api_key
)

DEBUG_MESSAGES = os.environ.get('DEBUG_MESSAGES') == 'true'




#USE_STABLE_MODELS=false FLASK_APP=grok3.py flask run -p 5003 -h 0.0.0.0
# Flag to switch between experimental and stable model lists
USE_STABLE_MODELS = os.environ.get('USE_STABLE_MODELS') == 'true'

MODELS_EXPERIMENTAL = [
    "meta-llama/llama-4-maverick-17b-128e-instruct:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "tngtech/deepseek-r1t-chimera:free",
    "deepseek/deepseek-r1-0528:free",
    "deepseek/deepseek-r1-distill-llama-70b:free",
    "qwen/qwen3-14b:free",
    "google/gemma-3-12b-it:free",    
    "mistralai/devstral-small:free",
    "minimax/minimax-m1",
    "x-ai/grok-3-mini-beta",
    "openai/gpt-4o-mini",
    "anthropic/claude-3-5-haiku",
    "google/gemini-2.5-flash-lite-preview-06-17",
]

MODELS_STABLE = [
    "tngtech/deepseek-r1t-chimera:free",
    "google/gemini-2.5-flash-lite-preview-06-17",
    "x-ai/grok-3-mini-beta",
    "openai/gpt-4o-mini",
    "anthropic/claude-3-5-haiku",    
]

MODELS = MODELS_STABLE if USE_STABLE_MODELS else MODELS_EXPERIMENTAL

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
        if DEBUG_MESSAGES:
            print(f"[ask_grok] model={model!r}, messages={messages!r}")
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )
        if DEBUG_MESSAGES:
            print(f"[ask_grok] response content length={len(response.choices[0].message.content)}")
        print(f"[ask_grok] token usage: {response.usage}")
        return response.choices[0].message.content
    except openai.NotFoundError as e:
        if DEBUG_MESSAGES:
            print(f"[ask_grok] NotFoundError: {e}")
        return f"API Error: {e}"
    except Exception as e:
        if DEBUG_MESSAGES:
            print(f"[ask_grok] Exception: {e}")
        return f"Unexpected Error: {e}"




def serve_index_with_config():
    try:
        index_path = Path(app.static_folder) / 'index.html'
        with open(index_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Prepare appConfig script
        # Ensure MODELS is JSON serializable (it should be a list of strings)
        models_json = json.dumps(MODELS)
        selected_model_json = json.dumps(MODELS[0]) # Default model for initial load

        app_config_script = f'''<script>
          window.appConfig = {{
            models: {models_json},
            selectedModel: {selected_model_json}
          }};
        </script>'''

        # Inject script before closing body tag or head tag
        if '</body>' in html_content:
            html_content = html_content.replace('</body>', app_config_script + '</body>')
        elif '</head>' in html_content: # Fallback if no body tag (less likely for full HTML page)
            html_content = html_content.replace('</head>', app_config_script + '</head>')
        else: # Fallback: append to the end
            html_content += app_config_script

        return Response(html_content, mimetype='text/html')
    except FileNotFoundError:
        return "index.html not found in static folder", 404
    except Exception as e:
        print(f"Error serving index with config: {e}")
        return "Internal server error", 500

@app.route("/", methods=["GET"])
def index():
    return serve_index_with_config()

@app.route("/api/title_summary", methods=["POST"])
def api_title_summary():
    data = request.get_json()
    if DEBUG_MESSAGES:
        print('[FLASK] /api/title_summary received:', data)
    messages = data.get("messages", [])
    prompt = (
        "请根据以下对话内容，自动归纳一个简明、概括性的标题（10字以内），只返回标题本身，不要加任何解释：\n"
        + '\n'.join(f"[{m.get('role','')}] {m.get('content','')}" for m in messages)
    )
    title = ask_grok("google/gemini-flash-1.5", [{"role": "user", "content": prompt}])
    # 只取前10字，去除空白
    title = (title or "新会话").strip().replace("\n", "").replace("：", ":")[:10]
    if DEBUG_MESSAGES:
        print('[FLASK] /api/title_summary response:', title)
    return jsonify({"title": title or "新会话"})

@app.route("/api/chat", methods=["POST"])
def api_chat():
    if DEBUG_MESSAGES:
        print('[FLASK] /api/chat received:', request.get_json())
    data = request.get_json()
    question = data.get("question", "").strip()
    selected_model = data.get("model", "google/gemini-flash-1.5")
    history = data.get("history", [])
    conversation_id = data.get("conversation_id") or "default"
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
    # 拼接历史+当前
    history.append({"role": "user", "content": question})
    messages = summarize_history(history, max_chars=2000)
    # 保存用户消息
    import time
    
    if DEBUG_MESSAGES:
        print(f"[api_chat] question={question!r}")
        print(f"[api_chat] model={selected_model!r}")
        print(f"[api_chat] history={history!r}")
    def generate():
        full_answer = ''
        model_name = selected_model # Capture the model name
        total_tokens = 0

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=True
            )
            for chunk in response:
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_answer += content
                    yield content
                
            # Manual token counting using tiktoken
            import tiktoken

            try:
                encoding = tiktoken.encoding_for_model(model_name)
            except KeyError:
                encoding = tiktoken.get_encoding("cl100k_base") # Fallback for unknown models

            # Calculate input tokens
            input_tokens = 0
            for message in messages:
                input_tokens += len(encoding.encode(message.get('content', '')))
                input_tokens += 4 # Every message follows <im_start>{role/name}\n{content}<im_end>\n
            input_tokens += 2 # Every reply starts with <im_start>assistant\n
            # Calculate output tokens
            output_tokens = len(encoding.encode(full_answer))
            total_tokens = input_tokens + output_tokens

            yield f"\n\n(Model: {model_name}, Tokens: {total_tokens})\n"

        except openai.NotFoundError as e:
            yield f"API Error: {e}"
        except Exception as e:
            yield f"Unexpected Error: {e}"
        
    return Response(generate(), mimetype='text/plain')

@app.route('/<path:path>')
def serve_react_app(path):
    # Serve static files directly if they exist
    static_file_path = Path(app.static_folder) / path
    if static_file_path.exists() and static_file_path.is_file():
        return send_from_directory(app.static_folder, path)
    # For any other path (including client-side routes or explicit index.html), serve the main app shell
    return serve_index_with_config()



import socket

def find_free_port(start_port=5000, max_tries=10):
    port = start_port
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('0.0.0.0', port)) != 0:
                return port
            port += 1
    raise RuntimeError("No free port found in range.")
