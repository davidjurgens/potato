#!/usr/bin/env python3
import json
import os
from datetime import datetime
from pathlib import Path

print("=" * 70)
print("  提取11月25日的数据")
print("=" * 70)
print()

# 读取所有提交数据
user_submissions = {}
with open("annotated_instances.jsonl", 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip():
            data = json.loads(line)
            user_id = data.get('user_id', '')
            user_submissions[user_id] = data

print(f"📊 总提交数: {len(user_submissions)}")
print()

# 找出11月25日的用户目录
nov25_data = []
for item in Path(".").iterdir():
    if item.is_dir() and item.name != "." and '&' in item.name:
        user_dir = item.name
        mtime = datetime.fromtimestamp(item.stat().st_mtime)
        
        # 只要11月25日的
        if mtime.strftime("%Y-%m-%d") == "2025-11-25":
            # 查找该用户的提交数据
            matching_submission = None
            for user_id, submission in user_submissions.items():
                if user_id.startswith(user_dir.split('&')[0]):
                    matching_submission = submission
                    break
            
            if matching_submission and 'label_annotations' in matching_submission:
                prompt = matching_submission.get('label_annotations', {}).get('malicious_prompt', {}).get('text_box', '')
                if prompt:  # 只要有实际提交的
                    nov25_data.append({
                        'user_id': matching_submission.get('user_id', ''),
                        'prolific_pid': user_dir.split('&')[0],
                        'submission_timestamp': mtime.strftime("%Y-%m-%d %H:%M:%S"),
                        'instance_id': matching_submission.get('instance_id', ''),
                        'displayed_text': matching_submission.get('displayed_text', ''),
                        'scenario_name': matching_submission.get('scenario_name', ''),
                        'standard_name': matching_submission.get('standard_name', ''),
                        'malicious_prompt': prompt,
                        'time_spent': matching_submission.get('behavioral_data', {}).get('time_string', 'N/A')
                    })

# 按时间排序
nov25_data.sort(key=lambda x: x['submission_timestamp'], reverse=True)

print(f"✅ 找到 {len(nov25_data)} 条11月25日的有效提交")
print()

# 保存JSON
output_json = "../../user_data/nov25_submissions.json"
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(nov25_data, f, indent=2, ensure_ascii=False)

print(f"💾 JSON已保存: {output_json}")

# 保存CSV
import csv
output_csv = "../../user_data/nov25_submissions.csv"
if nov25_data:
    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=nov25_data[0].keys())
        writer.writeheader()
        writer.writerows(nov25_data)
    print(f"💾 CSV已保存: {output_csv}")

print()
print("📋 11月25日提交列表:")
print("-" * 70)
for i, item in enumerate(nov25_data, 1):
    print(f"\n{i}. ⏰ {item['submission_timestamp']}")
    print(f"   User: {item['prolific_pid'][:20]}...")
    print(f"   Scenario: {item.get('scenario_name', 'N/A')}")
    print(f"   Standard: {item.get('standard_name', 'N/A')}")
    print(f"   Prompt: {item['malicious_prompt'][:60]}...")
    print(f"   Time spent: {item['time_spent']}")

print()
print("=" * 70)
print("✅ 完成！")
print("=" * 70)
