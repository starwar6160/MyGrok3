import os
import json
from flask import Blueprint, request, jsonify, render_template, Response, stream_with_context
import openai
from datetime import datetime, timedelta

# Create a Blueprint for translation routes
translation_bp = Blueprint('translation', __name__)

# Configure the OpenRouter API client
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=openai_api_key
)

# Define models
# Model A: For translation between Chinese and English
TRANSLATION_MODEL = "google/gemini-flash-1.5-8b"  # Efficient model for translation
# Model B: English-only model
ENGLISH_MODEL = "openai/gpt-4o-mini"  # Handles English content only

# Route to serve the translation page
@translation_bp.route('/')
def translation_page():
    return render_template('translation.html')

# API endpoint for direct translation between Chinese and English
@translation_bp.route('/api/translate', methods=['POST'])
def api_translate():
    try:
        data = request.json
        text = data.get('text', '')
        source_lang = data.get('source_lang', 'auto')
        target_lang = data.get('target_lang', 'en')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
            
        # Auto-detect language if set to auto
        if source_lang == 'auto':
            # Simple detection based on characters
            if any('\u4e00' <= char <= '\u9fff' for char in text):
                source_lang = 'zh'
            else:
                source_lang = 'en'
        
        # Construct the translation prompt
        if source_lang == target_lang:
            return jsonify({'translated_text': text})
            
        messages = [
            {"role": "system", "content": f"You are a professional translator. Translate the text from {source_lang} to {target_lang}. Provide only the translation without any explanations or additional notes."},
            {"role": "user", "content": text}
        ]
        
        # Call the translation model (Model A)
        response = client.chat.completions.create(
            model=TRANSLATION_MODEL,
            messages=messages,
            max_tokens=2000,
            temperature=0.3
        )
        
        translated_text = response.choices[0].message.content
        return jsonify({
            'translated_text': translated_text,
            'source_lang': source_lang,
            'target_lang': target_lang
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoint for processing Chinese input through English-only model
@translation_bp.route('/api/process-with-english-model', methods=['POST'])
def api_process_with_english_model():
    data = request.json
    user_input = data.get('text', '')
    stream_mode = data.get('stream', False)
    
    if not user_input:
        return jsonify({'error': 'No input provided'}), 400
    
    # Check if input contains Chinese characters
    contains_chinese = any('\u4e00' <= char <= '\u9fff' for char in user_input)
    
    def generate():
        try:
            translated_input = user_input
            
            # Step 1: If Chinese input, translate to English using Model A
            if contains_chinese:
                translate_messages = [
                    {"role": "system", "content": "You are a professional translator. Translate the following Chinese text to English accurately. Provide only the translation without any explanations."},
                    {"role": "user", "content": user_input}
                ]
                
                translate_response = client.chat.completions.create(
                    model=TRANSLATION_MODEL,
                    messages=translate_messages,
                    max_tokens=1500,
                    temperature=0.3
                )
                
                translated_input = translate_response.choices[0].message.content
                if stream_mode:
                    yield f"[Translated query to English]: {translated_input}\n\n"
            
            # Step 2: Process with English-only model (Model B)
            english_messages = [
                {"role": "system", "content": "You are a helpful assistant that only responds in English."},
                {"role": "user", "content": translated_input}
            ]
            
            response = client.chat.completions.create(
                model=ENGLISH_MODEL,
                messages=english_messages,
                max_tokens=2000,
                temperature=0.7,
                stream=stream_mode
            )
            
            english_output = ""
            
            if stream_mode:
                yield "[English Model Response]:\n"
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        english_output += content
                        yield content
            else:
                english_output = response.choices[0].message.content
                yield english_output
            
            # Step 3: If original input was Chinese, translate the English output back to Chinese
            if contains_chinese and english_output:
                yield "\n\n[Translating response to Chinese...]\n\n"
                
                back_translate_messages = [
                    {"role": "system", "content": "You are a professional translator. Translate the following English text to Chinese accurately. Provide only the translation without any explanations."},
                    {"role": "user", "content": english_output}
                ]
                
                back_translate_response = client.chat.completions.create(
                    model=TRANSLATION_MODEL, 
                    messages=back_translate_messages,
                    max_tokens=2000,
                    temperature=0.3
                )
                
                chinese_output = back_translate_response.choices[0].message.content
                yield f"[中文翻译]:\n{chinese_output}"
                
        except Exception as e:
            yield f"Error: {str(e)}"
    
    if stream_mode:
        return Response(stream_with_context(generate()), mimetype='text/plain')
    else:
        response_text = "".join(list(generate()))
        return jsonify({'response': response_text})

# Function to register the blueprint with a Flask app
def init_translation_api(app):
    app.register_blueprint(translation_bp, url_prefix='/translation')
