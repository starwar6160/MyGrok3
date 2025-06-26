import openai
import os
import hashlib
import json
import tiktoken
from flask import Flask, render_template, request, Response, stream_with_context, send_from_directory, jsonify, g
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from translation_api import init_translation_api
from chat_api import register_blueprint as register_chat_blueprint
from cost_calculator import CostTracker, initialize_prices
from chat_handler import generate_chat_response, FinalStats
from session_store import get_session_store
from openrouter_manager import (
    ensure_openrouter_models,
    get_1m_output_cost,
    suggest_cheaper_models,
    openrouter_models_cache,
)
import uuid

import logging_config
logger = logging_config.configure_logger(__name__)

# === React 静态页面托管 ===
app = Flask(__name__, static_folder="frontend/build", template_folder="templates")
app.secret_key = 'your_secret_key'  # Replace with a real secret key
app.config['JSON_AS_ASCII'] = False

# 允许跨域
try:
    from flask_cors import CORS
    CORS(app)
except ImportError:
    pass  # 如果没装CORS，先不报错

# Initialize expensive resources once at startup
get_session_store()
initialize_prices()

# Before request handler to set session_id
@app.before_request
def before_request():
    from flask import g, session
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    g.session_id = session['session_id']

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
#USE_STABLE_MODELS=false FLASK_APP=grok3.py flask run -p 5005 -h 0.0.0.0
# Flag to switch between experimental and stable model lists
USE_STABLE_MODELS = os.environ.get('USE_STABLE_MODELS') == 'true'

from models_config import MODELS_EXPERIMENTAL, MODELS_STABLE

MODELS = MODELS_STABLE if USE_STABLE_MODELS else MODELS_EXPERIMENTAL
DEFAULT_MODEL = MODELS[0]

# 简单 LLM cache（可换成 Redis 等）
llm_cache = {}

# 缓存大小限制和过期时间
LLM_CACHE_MAX_SIZE = 1000  # 最大缓存条目数
LLM_CACHE_EXPIRY_SECONDS = 3600  # 缓存过期时间（1小时）

# OpenRouter pricing and model management is now in MyGrok3.openrouter_manager module



def get_llm_cache_key(model, messages):
    # 用模型+消息内容哈希做key，使用更安全的SHA-256哈希算法
    key_src = model + json.dumps(messages, ensure_ascii=False)
    return hashlib.sha256(key_src.encode('utf-8')).hexdigest()

def get_llm_cached(model, messages, stream=False):
    # 清理过期缓存
    clean_expired_cache()
    
    # 验证消息格式
    validated_messages = validate_messages(messages)
    
    # 临时禁用缓存，强制每次都请求 LLM
    if stream:
        chunks = []
        for chunk in ask_grok_stream(model, validated_messages):
            chunks.append(chunk)
            yield chunk
    else:
        return ask_grok(model, validated_messages)

def clean_expired_cache():
    """清理过期缓存和超出大小限制的缓存"""
    global llm_cache
    current_time = time.time()
    
    # 删除过期缓存
    expired_keys = []
    for key, value in llm_cache.items():
        if 'timestamp' in value and current_time - value['timestamp'] > LLM_CACHE_EXPIRY_SECONDS:
            expired_keys.append(key)
    
    for key in expired_keys:
        del llm_cache[key]
    
    # 如果缓存大小超出限制，删除最早的缓存
    if len(llm_cache) > LLM_CACHE_MAX_SIZE:
        # 按时间戳排序
        sorted_cache = sorted(llm_cache.items(), key=lambda x: x[1].get('timestamp', 0))
        # 删除最早的缓存，直到大小符合限制
        for key, _ in sorted_cache[:len(llm_cache) - LLM_CACHE_MAX_SIZE]:
            del llm_cache[key]

def validate_messages(messages):
    """验证消息格式，防止注入恶意内容"""
    if not isinstance(messages, list):
        return []
    
    validated = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
            
        # 只允许有效的角色
        role = msg.get('role')
        if role not in ['system', 'user', 'assistant']:
            continue
            
        # 确保内容是字符串且长度合理
        content = msg.get('content')
        if not isinstance(content, str):
            content = ''
        if len(content) > 100000:  # 设置合理的长度上限
            content = content[:100000] + '... [内容已截断]'
            
        validated.append({'role': role, 'content': content})
    
    return validated

# 自动摘要历史，超 max_chars 时用 LLM 总结前面的，仅保留最近3条原文
# 实际生产建议用 LLM 生成摘要，这里用拼接模拟

def summarize_history(history, max_chars=4000, keep_last_n=8, summary_max_len=1000):
    # 验证输入，确保history是有效的列表类型
    if not isinstance(history, list):
        return []
        
    # 移除已有 system 摘要
    filtered = [msg for msg in history if isinstance(msg, dict) and msg.get('role') != 'system']
    
    # 验证所有消息内容，确保安全性
    filtered = validate_messages(filtered)
    
    total_chars = sum(len(msg.get('content', '')) for msg in filtered)
    if total_chars <= max_chars:
        return filtered
        
    # 保留最近N条，前面合并成摘要
    recent = filtered[-keep_last_n:] if keep_last_n > 0 else []
    to_summarize = filtered[:-keep_last_n] if keep_last_n > 0 else filtered
    
    if not to_summarize:
        return recent
        
    # 限制要摘要的内容大小，防止请求过大
    max_to_summarize_chars = 50000  # 设置一个合理的上限
    current_chars = 0
    limited_to_summarize = []
    
    for msg in to_summarize:
        msg_content = msg.get('content', '')
        msg_chars = len(msg_content)
        
        if current_chars + msg_chars <= max_to_summarize_chars:
            limited_to_summarize.append(msg)
            current_chars += msg_chars
        else:
            # 如果这条消息会导致超出限制，只取部分内容
            chars_to_take = max_to_summarize_chars - current_chars
            if chars_to_take > 0:
                truncated_msg = msg.copy()
                truncated_msg['content'] = msg_content[:chars_to_take] + '... [内容已截断]'
                limited_to_summarize.append(truncated_msg)
            break
    
    # 构建安全的摘要提示
    summary_prompt = (
        f"请用简明但尽量保留细节的方式总结以下多轮对话内容，摘要长度不超过{summary_max_len}字，便于后续上下文继续：\n"
    )
    
    for msg in limited_to_summarize:
        role = msg.get('role', '')
        content = msg.get('content', '')[:10000]  # 限制每条消息在提示中的长度
        summary_prompt += f"[{role}]: {content}\n"
    
    try:
        summary_text = get_llm_cached('grok-3-mini', [{"role": "user", "content": summary_prompt}])
        # 验证摘要文本
        if not isinstance(summary_text, str):
            summary_text = "历史对话摘要生成失败"
        elif len(summary_text) > summary_max_len:
            summary_text = summary_text[:summary_max_len] + "..."
    except Exception as e:
        # 处理摘要生成失败的情况
        summary_text = f"历史对话摘要生成失败: {str(e)[:100]}"
    
    summary = {'role': 'system', 'content': f'历史摘要：{summary_text}'}
    new_history = [summary] + recent
    
    # 如果还超长，递归摘要，但限制递归深度防止栈溢出
    if sum(len(msg.get('content', '')) for msg in new_history) > max_chars:
        # 添加递归深度追踪，防止无限递归
        recursion_depth = getattr(summarize_history, '_recursion_depth', 0) + 1
        if recursion_depth > 3:  # 限制最大递归深度
            # 如果递归过深，直接截断历史
            return new_history[-keep_last_n:] if keep_last_n > 0 else []
        
        # 记录递归深度
        summarize_history._recursion_depth = recursion_depth
        result = summarize_history(new_history, max_chars, keep_last_n, summary_max_len)
        # 重置递归深度
        summarize_history._recursion_depth = 0
        return result
    
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



@app.route('/<path:path>')
def serve_react_app(path):
    # Serve static files directly if they exist
    static_file_path = Path(app.static_folder) / path
    if static_file_path.exists() and static_file_path.is_file():
        return send_from_directory(app.static_folder, path)
    # For any other path (including client-side routes or explicit index.html), serve the main app shell
    return serve_index_with_config()



import socket

# Register Chat API blueprint
register_chat_blueprint(app)

# Initialize translation API routes
init_translation_api(app)

def find_free_port(start_port=5000, max_tries=10):
    port = start_port
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('0.0.0.0', port)) != 0:
                return port
            port += 1
    raise RuntimeError("No free port found in range.")
