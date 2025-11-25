#!/usr/bin/env python3
import json
import os
from datetime import datetime
from pathlib import Path

print("=" * 60)
print("  收集今天的新数据")
print("=" * 60)
print()

# 获取今天的日期
today = datetime.now().strftime("%Y-%m-%d")
print(f"📅 今天日期: {today}")
print()

# 查找今天的新用户目录
new_users = []
for item in Path(".").iterdir():
    if item.is_dir() and item.name != ".":
        # 检查目录修改时间
        mtime = datetime.fromtimestamp(item.stat().st_mtime)
        if mtime.strftime("%Y-%m-%d") == today:
            new_users.append(item)

print(f"✅ 找到 {len(new_users)} 个今天的新用户")
print()

# 收集数据
all_data = []
for user_dir in sorted(new_users, key=lambda x: x.stat().st_mtime, reverse=True):
    json_file = user_dir / "assigned_user_data.json"
    if json_file.exists():
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # 提取malicious_prompt
            for key, value in data.items():
                if isinstance(value, dict) and 'label_annotations' in value:
                    prompt_data = value['label_annotations'].get('malicious_prompt', {})
                    if 'text_box' in prompt_data:
                        all_data.append({
                            'user_id': value.get('user_id', 'unknown'),
                            'prolific_pid': user_dir.name.split('&')[0],
                            'timestamp': datetime.fromtimestamp(user_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            'instance_id': value.get('id', 'unknown'),
                            'scenario_name': value.get('scenario_name', ''),
                            'standard_name': value.get('standard_name', ''),
                            'malicious_prompt': prompt_data['text_box']
                        })

print(f"📝 收集到 {len(all_data)} 条malicious prompts")
print()

# 保存数据
output_file = f"collected_today_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False)

print(f"💾 数据已保存到: {output_file}")
print()

# 显示统计
print("📊 数据统计:")
print(f"  • 总用户数: {len(new_users)}")
print(f"  • 总提交数: {len(all_data)}")
print()

# 显示最近几条
print("📋 最新的3条提交预览:")
print("-" * 60)
for i, item in enumerate(all_data[:3], 1):
    print(f"\n{i}. {item['timestamp']} - {item['prolific_pid'][:16]}...")
    print(f"   Scenario: {item['scenario_name']}")
    print(f"   Standard: {item['standard_name']}")
    print(f"   Prompt: {item['malicious_prompt'][:80]}...")

print()
print("=" * 60)
print(f"✅ 完成！查看完整数据: cat {output_file} | jq .")
print("=" * 60)
