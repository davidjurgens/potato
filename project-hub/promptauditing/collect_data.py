#!/usr/bin/env python3
"""
收集所有用户提交的malicious prompt数据
"""
import json
import csv
from pathlib import Path
from datetime import datetime

# 配置路径
ANNOTATION_DIR = Path("annotation_output/full")
INPUT_FILE = ANNOTATION_DIR / "annotated_instances.jsonl"
OUTPUT_CSV = f"collected_malicious_prompts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
OUTPUT_JSON = f"collected_malicious_prompts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def collect_data():
    """收集所有提交的数据"""
    
    if not INPUT_FILE.exists():
        print(f"❌ 文件不存在: {INPUT_FILE}")
        print(f"请确保路径正确，当前工作目录: {Path.cwd()}")
        return
    
    collected_data = []
    
    print(f"📖 正在读取文件: {INPUT_FILE}")
    
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
                
            try:
                data = json.loads(line)
                
                # 提取关键信息
                user_id = data.get('user_id', '')
                instance_id = data.get('instance_id', '')
                displayed_text = data.get('displayed_text', '')
                
                # 提取用户输入的malicious prompt
                malicious_prompt = ''
                if 'label_annotations' in data and 'malicious_prompt' in data['label_annotations']:
                    malicious_prompt = data['label_annotations']['malicious_prompt'].get('text_box', '')
                
                # 提取时间信息
                time_spent = ''
                if 'behavioral_data' in data:
                    time_spent = data['behavioral_data'].get('time_string', '')
                
                collected_data.append({
                    'user_id': user_id,
                    'instance_id': instance_id,
                    'displayed_text': displayed_text,
                    'malicious_prompt': malicious_prompt,
                    'time_spent': time_spent,
                    'prompt_length': len(malicious_prompt),
                })
                
            except json.JSONDecodeError as e:
                print(f"⚠️  第{line_num}行JSON解析错误: {e}")
                continue
    
    print(f"\n✅ 成功收集 {len(collected_data)} 条数据")
    
    # 保存为CSV
    if collected_data:
        with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'user_id', 'instance_id', 'displayed_text', 
                'malicious_prompt', 'time_spent', 'prompt_length'
            ])
            writer.writeheader()
            writer.writerows(collected_data)
        
        print(f"💾 CSV文件已保存: {OUTPUT_CSV}")
        
        # 保存为JSON（更易读）
        with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(collected_data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 JSON文件已保存: {OUTPUT_JSON}")
        
        # 打印统计信息
        print(f"\n📊 统计信息:")
        print(f"   总数据条数: {len(collected_data)}")
        print(f"   唯一用户数: {len(set(d['user_id'] for d in collected_data))}")
        print(f"   平均prompt长度: {sum(d['prompt_length'] for d in collected_data) / len(collected_data):.1f} 字符")
        
        # 显示前3条数据
        print(f"\n📝 前3条数据示例:")
        for i, item in enumerate(collected_data[:3], 1):
            print(f"\n   [{i}] User: {item['user_id'][:20]}...")
            print(f"       Instance: {item['instance_id']}")
            print(f"       Prompt: {item['malicious_prompt'][:100]}...")
            print(f"       Time: {item['time_spent']}")
    else:
        print("⚠️  没有找到任何数据")

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 收集Malicious Prompt数据")
    print("=" * 60)
    collect_data()
    print("\n" + "=" * 60)
    print("✨ 完成!")
    print("=" * 60)

