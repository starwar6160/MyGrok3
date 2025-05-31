import redis
import json
from datetime import datetime, timedelta, timezone  # 导入 timezone 以支持 UTC

# 连接到本地 Redis 服务器（Docker 中的 myredis，端口 6379）
try:
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)  # decode_responses=True 用于自动解码字符串
    r.ping()  # 测试连接
except Exception as e:
    print("连接 Redis 失败，请确保 Redis 容器正在运行：", e)
    exit()

def is_within_time_limit(timestamp_str, hours=1):
    """检查时间戳是否在指定小时数内"""
    try:
        # 解析时间戳（假设 ISO 8601 格式）
        message_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))  # 兼容可能的 Z (UTC)
        
        # 如果 message_time 是 naive 对象，将其转换为 aware 对象（假设 UTC）
        if message_time.tzinfo is None:  # 检查是否是 naive
            message_time = message_time.replace(tzinfo=timezone.utc)  # 转换为 UTC aware
        
        now = datetime.now(timezone.utc)  # 使用 timezone-aware 对象
        time_limit = now - timedelta(hours=hours)
        return message_time > time_limit  # 现在都是 aware 对象，可以安全比较
    except ValueError:
        print(f"时间戳解析失败: {timestamp_str}")
        return False

# 获取所有相关键（例如，messages:* 和 conversation:*）
def get_relevant_keys():
    keys = r.keys('messages:*') + r.keys('conversation:*')  # 获取匹配的键
    return keys

# 主函数：获取并显示指定时间内的对话
def display_recent_conversations(hours=1):
    keys = get_relevant_keys()
    
    if not keys:
        print(f"没有找到相关键（messages:* 或 conversation:*）。")
        return
    
    print(f"显示过去 {hours} 小时内的对话：")
    
    for key in keys:
        key_type = r.type(key)
        
        if key_type == 'list' and key.startswith('messages:'):
            # 处理 messages:* 键（列表）
            items = r.lrange(key, 0, -1)  # 获取列表所有元素
            recent_items = []
            
            for item in items:
                try:
                    data = json.loads(item)  # 解析 JSON
                    timestamp = data.get('timestamp')
                    if timestamp and is_within_time_limit(timestamp, hours):
                        recent_items.append(data)
                except json.JSONDecodeError:
                    print(f"JSON 解析错误 for key {key}.")
            
            if recent_items:
                print(f"\n键: {key} (类型: 列表)")
                for item in recent_items:
                    print(f"  ID: {item.get('id')}")
                    print(f"  角色: {item.get('role')}")
                    print(f"  内容: {item.get('content')}")  # 中文内容会自动显示
                    print(f"  时间戳: {item.get('timestamp')}")
                    print("  ---")
            else:
                print(f"键 {key} 中没有在过去 {hours} 小时内的项目。")
        
        elif key_type == 'hash' and key.startswith('conversation:'):
            # 处理 conversation:* 键（哈希） - 只显示哈希内容
            data = r.hgetall(key)  # 获取哈希所有字段和值
            if data:  # 如果哈希有内容
                print(f"\n键: {key} (类型: 哈希)")
                for field, value in data.items():
                    print(f"  字段: {field}，值: {value}")
            else:
                print(f"键 {key} 中没有数据。")
        else:
            print(f"键 {key} 的类型 {key_type} 不处理。")

# 运行主函数
if __name__ == "__main__":
    try:
        display_recent_conversations(hours=1)  # 默认 1 小时，您可以修改参数
    except Exception as e:
        print("发生错误：", e)

print("数据处理完成。")

