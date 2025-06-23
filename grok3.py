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



#screen -D -r 2304929
#USE_STABLE_MODELS=false FLASK_APP=grok3.py flask run -p 5003 -h 0.0.0.0
# Flag to switch between experimental and stable model lists
USE_STABLE_MODELS = os.environ.get('USE_STABLE_MODELS') == 'true'

MODELS_EXPERIMENTAL = [
    #便宜，而且能正确回答9.9和9.11哪一个大的模型：
    "mistralai/ministral-8b",    #10/10
    "mistralai/mixtral-8x7b-instruct",#8/24
    "google/gemini-2.5-flash-lite-preview-06-17",   #10/40    
    "qwen/qwen3-14b",   #6/24
    "moonshotai/kimi-dev-72b:free",   
    "deepseek/deepseek-r1-distill-llama-70b",   #10/40
    #便宜，但比前面的贵的经济型模型
    "openai/gpt-4o-mini",#15/60    
    "x-ai/grok-3-mini",#30/50
    "thedrummer/unslopnemo-12b",#45/45    
    "deepseek/deepseek-r1-0528:free",    #55/219    
    "minimax/minimax-m1",#30/165
    "mistralai/mixtral-8x22b-instruct",#90/90
    #便宜，但是无法正确回答9.9和9.11哪一个大的模型：
    "google/gemini-flash-1.5-8b",    #3.8/15
    "google/gemma-3-12b-it",    #5/10
    "mistralai/devstral-small",#6/12

]
#"tngtech/deepseek-r1t-chimera:free",
#    "deepseek/deepseek-chat-v3-0324",#27/110    
# microsoft/wizardlm-2-8x22b

MODELS_STABLE = [
    "google/gemini-2.5-flash-lite-preview-06-17",
    "qwen/qwen3-14b",   #6/24
    "openai/gpt-4o-mini",
    "x-ai/grok-3-mini",    
    "deepseek/deepseek-r1-distill-llama-70b:free",
    "thedrummer/unslopnemo-12b",#45/45    
]

MODELS = MODELS_STABLE if USE_STABLE_MODELS else MODELS_EXPERIMENTAL
DEFAULT_MODEL = "google/gemini-2.5-flash-lite-preview-06-17"

# 简单 LLM cache（可换成 Redis 等）
llm_cache = {}

# === OpenRouter模型价格缓存与每日刷新 ===
import threading
import time
from datetime import datetime, timedelta

openrouter_models_cache = {
    'models': [],  # 模型完整信息
    'last_fetch': None,  # 上次拉取时间
    'price_dict': {},    # {model_name: {'input': float, 'output': float}}
}

OPENROUTER_PRICE_CACHE_PATH = 'openrouter_model_prices.json'

# 保存当天价格到json文件
def save_openrouter_price_cache():
    from datetime import datetime
    data = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'models': openrouter_models_cache['models'],
        'price_dict': openrouter_models_cache['price_dict']
    }
    try:
        with open(OPENROUTER_PRICE_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        if DEBUG_MESSAGES:
            print(f'[OpenRouter] Failed to save price cache: {e}')

# 加载当天价格json文件
def load_openrouter_price_cache():
    from datetime import datetime
    import os
    if not os.path.exists(OPENROUTER_PRICE_CACHE_PATH):
        return False
    try:
        with open(OPENROUTER_PRICE_CACHE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        today = datetime.now().strftime('%Y-%m-%d')
        if data.get('date') == today:
            openrouter_models_cache['models'] = data.get('models', [])
            openrouter_models_cache['price_dict'] = data.get('price_dict', {})
            openrouter_models_cache['last_fetch'] = datetime.now()
            if DEBUG_MESSAGES:
                print('[OpenRouter] Loaded today price cache from file')
            return True
    except Exception as e:
        if DEBUG_MESSAGES:
            print(f'[OpenRouter] Failed to load price cache: {e}')
    return False


OPENROUTER_MODELS_API = "https://openrouter.ai/api/v1/models"

# 拉取OpenRouter模型列表及价格
def fetch_openrouter_models():
    import requests
    headers = {"Authorization": f"Bearer {openai_api_key}"}
    try:
        resp = requests.get(OPENROUTER_MODELS_API, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            openrouter_models_cache['models'] = data.get('data', [])
            openrouter_models_cache['last_fetch'] = datetime.now()
            price_dict = {}
            for m in openrouter_models_cache['models']:
                model_id = m.get('id')
                pricing = m.get('pricing', {})
                try:
                    input_price = float(pricing.get('prompt', 0))
                    output_price = float(pricing.get('completion', 0))
                except Exception:
                    input_price = output_price = 0
                price_dict[model_id] = {
                    'input': input_price,
                    'output': output_price
                }
            openrouter_models_cache['price_dict'] = price_dict
            if DEBUG_MESSAGES:
                print('[OpenRouter] Model pricing updated:', price_dict)
            save_openrouter_price_cache()
        else:
            if DEBUG_MESSAGES:
                print(f'[OpenRouter] Failed to fetch models: {resp.status_code}')
    except Exception as e:
        if DEBUG_MESSAGES:
            print(f'[OpenRouter] Exception fetching models: {e}')

# 定时每日自动刷新（守护线程）
def start_openrouter_model_refresh():
    def loop():
        while True:
            fetch_openrouter_models()
            time.sleep(24 * 60 * 60)  # 每24小时拉取一次
    t = threading.Thread(target=loop, daemon=True)
    t.start()

# 启动时先拉取一次并启动定时线程
def ensure_openrouter_models():
    # 若超24小时未拉取则强制拉取
    now = datetime.now()
    last = openrouter_models_cache.get('last_fetch')
    # 优先尝试加载当天缓存
    if not openrouter_models_cache['models'] or not openrouter_models_cache['price_dict']:
        loaded = load_openrouter_price_cache()
        if loaded:
            last = openrouter_models_cache.get('last_fetch')
    if not last or (now - last > timedelta(hours=24)):
        fetch_openrouter_models()
    if not getattr(ensure_openrouter_models, '_started', False):
        start_openrouter_model_refresh()
        ensure_openrouter_models._started = True

# 计算请求成本
def estimate_cost(model_name, input_tokens, output_tokens):
    ensure_openrouter_models()
    price_dict = openrouter_models_cache.get('price_dict', {})
    price = price_dict.get(model_name)
    if price:
        return input_tokens * price['input'] + output_tokens * price['output']
    return 0.0

# 获取1M输出token的价格
def get_1m_output_cost(model_name):
    ensure_openrouter_models()
    price_dict = openrouter_models_cache.get('price_dict', {})
    price = price_dict.get(model_name)
    if price:
        return price['output'] * 1_000_000
    return 0.0

# 获取更便宜的模型建议
def suggest_cheaper_models(current_model, max_output_cost=1.0):
    ensure_openrouter_models()
    price_dict = openrouter_models_cache.get('price_dict', {})
    cheaper = [m for m, v in price_dict.items() if v['output'] * 1_000_000 < max_output_cost and m != current_model]
    return cheaper[:2]  # 最多推荐2个


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
        selected_model_json = json.dumps(DEFAULT_MODEL) # Default model for initial load

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
    selected_model = data.get("model", "x-ai/grok-3-mini")
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
        # 会话累计成本缓存（放在闭包外，防止多次请求时丢失）
        if not hasattr(generate, 'session_total_cost'):
            generate.session_total_cost = 0.0

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=True
            )
            last_content = None
            for chunk in response:
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_answer += content
                    if last_content is not None:
                        yield last_content
                    last_content = content
            # 只yield最后一条统计和警告
            if last_content is not None:
                yield last_content
            
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

            # === 成本估算与高价警告 ===
            estimated_cost = estimate_cost(model_name, input_tokens, output_tokens)
            output_cost_per_1m = get_1m_output_cost(model_name)
            # 累加本会话成本
            generate.session_total_cost += estimated_cost
            warning_msg = ''
            warning_threshold = 0.05  # 单次请求警告阈值（美元）
            output_1m_threshold = 0.5  # 1M输出token高价阈值
            if estimated_cost > warning_threshold or output_cost_per_1m >= output_1m_threshold:
                # 新逻辑：随机推荐2个非free且输出成本<0.3美元的模型
                import random
                ensure_openrouter_models()
                price_dict = openrouter_models_cache.get('price_dict', {})
                # 强制转为float，过滤无效或异常数据，确保只推荐真实低价模型
                candidates = []
                for m, v in price_dict.items():
                    try:
                        if (
                            isinstance(v, dict)
                            and 'output' in v
                            and v['output'] is not None
                            and 'free' not in m
                            and m != model_name
                        ):
                            output_cost = float(v['output'])
                            if (output_cost * 1_000_000) < 0.3:
                                candidates.append(m)
                    except Exception:
                        continue

                random.shuffle(candidates)
                cheaper = candidates[:2]
                cheaper_str = '、'.join(cheaper) if cheaper else ''
                if output_cost_per_1m >= output_1m_threshold:
                    warning_msg = f"\n\n成本提示：当前模型输出成本较高，1M token 约 {output_cost_per_1m:.2f} 美元。"
                else:
                    warning_msg = f"\n\n请注意：本次对话预计输出成本较高（约 {estimated_cost:.8f} 美元）。"
                if cheaper_str:
                    warning_msg += f" 如需节省成本，请考虑切换到 {cheaper_str}。"
            # 新增累计成本输出（单位：美分）
            total_cost_cents = generate.session_total_cost * 100
            total_cost_msg = f"\n本会话累计成本：约 {total_cost_cents:.2f} 美分" if total_cost_cents > 0.1 else ""
            # 只在最后输出一次统计和警告
            yield f"\n\n(Model: {model_name}, Tokens: {total_tokens}){warning_msg}{total_cost_msg}\n"

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
