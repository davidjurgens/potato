#!/usr/bin/env python3
import json
from datetime import datetime
import os

print("=" * 60)
print("  从 annotated_instances.jsonl 提取今天的提交")
print("=" * 60)
print()

today = datetime.now().strftime("%Y-%m-%d")
print(f"📅 今天日期: {today}")

# 检查文件修改时间
file_mtime = datetime.fromtimestamp(os.path.getmtime("annotated_instances.jsonl"))
print(f"📄 文件最后修改: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')}")
print()

# 读取所有数据
all_submissions = []
with open("annotated_instances.jsonl", 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip():
            all_submissions.append(json.loads(line))

print(f"📊 文件中总提交数: {len(all_submissions)}")
print()

# 由于jsonl是追加模式，我们查看最后N条
print("📋 最后10条提交:")
print("-" * 60)
for i, item in enumerate(all_submissions[-10:], 1):
    user_id = item.get('user_id', 'unknown')
    prolific_pid = user_id.split('&')[0] if '&' in user_id else user_id
    prompt = item.get('label_annotations', {}).get('malicious_prompt', {}).get('text_box', 'N/A')
    time_spent = item.get('behavioral_data', {}).get('time_string', 'unknown')
    
    print(f"\n{len(all_submissions)-10+i}. User: {prolific_pid[:20]}...")
    print(f"   Prompt: {prompt[:60]}...")
    print(f"   {time_spent}")

print()
print("=" * 60)

# 让用户选择从哪条开始算是"新数据"
print()
print("💡 提示: 由于jsonl是追加模式，最新的数据在文件末尾")
print("如果你想提取最近N条数据，可以使用:")
print("  tail -N annotated_instances.jsonl > today_data.jsonl")
print()
print("例如，提取最后20条:")
print("  tail -20 annotated_instances.jsonl > today_20_submissions.jsonl")
print("=" * 60)
