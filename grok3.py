import openai
import os
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

# Function to query Grok model
def ask_grok_stream(model, prompt):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
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
def ask_grok(model, prompt):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}]
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

    # 流式API: POST JSON
    if request.method == "POST" and request.content_type and request.content_type.startswith("application/json"):
        data = request.get_json()
        question = data.get("question", "").strip()
        selected_model = data.get("model", "grok-3-mini")
        if not question:
            return Response("Please enter a question.", mimetype="text/plain"), 400
        return Response(stream_with_context(ask_grok_stream(selected_model, question)), mimetype='text/plain')

    # 普通表单POST
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        selected_model = request.form.get("model", "grok-3-mini")
        if not question:
            error = "Please enter a question."
        else:
            answer = ask_grok(selected_model, question)
    return render_template(
        "index.html",
        answer=answer,
        error=error,
        question=question,
        selected_model=selected_model
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
