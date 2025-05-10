import requests
import os
import sys

# 配置模型信息
PRIMARY_MODEL = "x-ai/grok-3-mini-beta"
SECONDARY_MODEL = "x-ai/grok-3-beta"
API_URL = "https://openrouter.ai/api/v1/chat/completions"  # 假设这是对话API端点（请根据实际调整）

def get_api_key():
    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        print("警告：未在环境变量中找到 OPENROUTER_API_KEY。")
        try:
            user_input = input("请输入您的 OpenRouter API KEY： ").strip()
        except KeyboardInterrupt:
            print("\n用户中断，退出程序。")
            sys.exit(1)
        if user_input:
            api_key = user_input
        else:
            print("未提供API KEY，退出程序。")
            sys.exit(1)
    return api_key

def check_model_availability(model_name, api_key):
    """
    简单验证模型是否可用（可以通过请求模型列表或直接请求测试调用）
    这里用请求模型列表的方式判断（实际可用性检测可能需要更复杂逻辑）
    """
    url = 'https://openrouter.ai/api/v1/models'
    headers = {
        'Authorization': f'Bearer {api_key}'
    }
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            models = resp.json()
            return any(model['id'] == model_name for model in models.get('data', []))
        else:
            return False
    except:
        return False

def chat_with_model(model, message, api_key):
    """
    发送对话请求到模型（请根据实际API调整请求体）
    """
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": message}]
        # 根据API实际需求调整参数
    }
    try:
        response = requests.post(API_URL, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            # 假设返回结构中有choices[0].message.content
            return result['choices'][0]['message']['content']
        else:
            print(f"请求模型失败，状态码：{response.status_code}，响应：{response.text}")
            return None
    except Exception as e:
        print(f"请求异常：{e}")
        return None

if __name__ == "__main__":
    api_key = get_api_key()

    # 检查模型可用性
    primary_available = check_model_availability(PRIMARY_MODEL, api_key)
    secondary_available = check_model_availability(SECONDARY_MODEL, api_key)

    # 选择模型
    current_model = None
    if primary_available:
        current_model = PRIMARY_MODEL
        print(f"优先使用模型：{PRIMARY_MODEL}")
    elif secondary_available:
        current_model = SECONDARY_MODEL
        print(f"模型 {PRIMARY_MODEL} 不可用，切换到备用模型：{SECONDARY_MODEL}")
    else:
        print("两个模型都不可用，程序退出。")
        sys.exit(1)

    print("开始对话，输入 '退出' 或 Ctrl+C 结束。")
    while True:
        try:
            user_input = input("你：")
            if user_input.strip().lower() == "退出":
                print("结束对话。")
                break
            response = chat_with_model(current_model, user_input, api_key)
            if response:
                print("模型：", response)
            else:
                print("未收到模型响应。")
        except KeyboardInterrupt:
            print("\n对话结束。")
            break
