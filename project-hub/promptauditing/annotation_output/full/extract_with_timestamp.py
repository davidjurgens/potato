#!/usr/bin/env python3
import json
import os
from datetime import datetime
from pathlib import Path

print("=" * 70)
print("  提取带时间戳的annotation数据")
print("=" * 70)
print()

# 读取annotated_instances.jsonl中的所有user_id
user_submissions = {}
with open("annotated_instances.jsonl", 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip():
            data = json.loads(line)
            user_id = data.get('user_id', '')
            user_submissions[user_id] = data

print(f"📊 总提交数: {len(user_submissions)}")
print()

# 遍历用户目录，获取文件系统时间戳
results = []
for item in Path(".").iterdir():
    if item.is_dir() and item.name != "." and '&' in item.name:
        user_dir = item.name
        
        # 查找该用户的提交数据
        matching_submission = None
        for user_id, submission in user_submissions.items():
            if user_id.startswith(user_dir.split('&')[0]):
                matching_submission = submission
                break
        
        if matching_submission:
            # 获取文件系统时间戳（目录的修改时间）
            mtime = datetime.fromtimestamp(item.stat().st_mtime)
            
            results.append({
                'user_id': matching_submission.get('user_id', ''),
                'prolific_pid': user_dir.split('&')[0],
                'submission_timestamp': mtime.strftime("%Y-%m-%d %H:%M:%S"),
                'instance_id': matching_submission.get('instance_id', ''),
                'displayed_text': matching_submission.get('displayed_text', ''),
                'malicious_prompt': matching_submission.get('label_annotations', {}).get('malicious_prompt', {}).get('text_box', ''),
                'time_spent': matching_submission.get('behavioral_data', {}).get('time_string', 'N/A')
            })

# 按时间排序
results.sort(key=lambda x: x['submission_timestamp'], reverse=True)

print(f"✅ 成功匹配 {len(results)} 条提交的时间戳")
print()

# 保存
output_file = f"submissions_with_timestamp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"💾 已保存到: {output_file}")
print()

# 显示统计
print("📅 提交时间分布:")
print("-" * 70)
by_date = {}
for r in results:
    date = r['submission_timestamp'].split()[0]
    by_date[date] = by_date.get(date, 0) + 1

for date in sorted(by_date.keys(), reverse=True):
    print(f"  {date}: {by_date[date]} 条提交")

print()
print("📋 最新的5条提交:")
print("-" * 70)
for i, r in enumerate(results[:5], 1):
    print(f"\n{i}. ⏰ {r['submission_timestamp']}")
    print(f"   User: {r['prolific_pid'][:20]}...")
    print(f"   Prompt: {r['malicious_prompt'][:60]}...")

print()
print("=" * 70)
