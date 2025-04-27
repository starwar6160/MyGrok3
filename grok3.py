import openai
import os
import hashlib
from flask import Flask, render_template, request, Response, stream_with_context
import json

# Initialize Flask app
app = Flask(__name__)

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

def summarize_history(history, max_chars=2000):
    total_chars = sum(len(msg.get('content', '')) for msg in history)
    if total_chars <= max_chars:
        return history
    # 保留最近3条，前面合并成摘要
    recent = history[-3:]
    to_summarize = history[:-3]
    summary_content = '\n'.join(f"[{msg['role']}]: {msg['content']}" for msg in to_summarize)
    summary = {'role': 'system', 'content': f'以上为历史摘要：{summary_content[:max_chars//2]}...'}
    return [summary] + recent

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
        if not question:
            return Response("Please enter a question.", mimetype="text/plain"), 400
        # 拼接历史+当前
        history.append({"role": "user", "content": question})
        messages = summarize_history(history, max_chars=2000)
        def stream_gen():
            for chunk in get_llm_cached(selected_model, messages, stream=True):
                yield chunk
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
