#!/usr/bin/env python3
"""
收集所有用户提交的malicious prompt数据
"""
import json
import csv
import shutil
from pathlib import Path
from datetime import datetime

# 配置路径
ANNOTATION_DIR = Path("annotation_output/full")
INPUT_FILE = ANNOTATION_DIR / "annotated_instances.jsonl"
DATA_FILE = Path("data_files/malicious_prompts.csv")
OUTPUT_DIR = Path("user_data")
OUTPUT_CSV = OUTPUT_DIR / f"collected_malicious_prompts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
OUTPUT_JSON = OUTPUT_DIR / f"collected_malicious_prompts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def clean_incomplete_sessions():
    """清理未完成的用户会话（静默模式）"""
    
    # 读取已完成标注的用户ID
    completed_user_ids = set()
    
    if INPUT_FILE.exists():
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        completed_user_ids.add(data.get('user_id'))
                    except json.JSONDecodeError:
                        pass
    
    # 扫描所有用户文件夹
    incomplete_folders = []
    for item in ANNOTATION_DIR.iterdir():
        if item.is_dir():
            folder_name = item.name
            # 跳过归档文件夹和特殊文件夹
            if folder_name not in ['archived_previous_data', '__pycache__']:
                if folder_name not in completed_user_ids:
                    incomplete_folders.append(folder_name)
    
    # 删除未完成的文件夹
    deleted_count = 0
    if incomplete_folders:
        print(f"🧹 清理未完成的会话: 发现 {len(incomplete_folders)} 个...")
        for folder_name in incomplete_folders:
            folder_path = ANNOTATION_DIR / folder_name
            try:
                shutil.rmtree(folder_path)
                deleted_count += 1
            except Exception:
                pass
        print(f"✅ 已删除 {deleted_count} 个未完成的会话")
    
    return deleted_count

def load_reference_data():
    """加载malicious_prompts.csv作为参考数据，获取scenario和standard信息"""
    reference_data = {}
    
    if not DATA_FILE.exists():
        print(f"⚠️  参考文件不存在: {DATA_FILE}")
        return reference_data
    
    print(f"📚 加载参考数据: {DATA_FILE}")
    
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            instance_id = row['id']
            reference_data[instance_id] = {
                'scenario_name': row.get('scenario_name', ''),
                'scenario_description': row.get('scenario_description', ''),
                'standard_name': row.get('standard_name', ''),
                'standard_description': row.get('description', ''),
            }
    
    print(f"✅ 加载了 {len(reference_data)} 条参考数据")
    return reference_data

def collect_data():
    """收集所有提交的数据"""
    
    # 创建输出目录
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"📁 输出目录: {OUTPUT_DIR}")
    
    # 清理未完成的会话
    clean_incomplete_sessions()
    
    if not INPUT_FILE.exists():
        print(f"❌ 文件不存在: {INPUT_FILE}")
        print(f"请确保路径正确，当前工作目录: {Path.cwd()}")
        return
    
    # 加载参考数据
    reference_data = load_reference_data()
    
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
                
                # 从参考数据获取scenario和standard信息
                ref_info = reference_data.get(instance_id, {})
                
                collected_data.append({
                    'user_id': user_id,
                    'instance_id': instance_id,
                    'scenario_name': ref_info.get('scenario_name', ''),
                    'scenario_description': ref_info.get('scenario_description', ''),
                    'standard_name': ref_info.get('standard_name', ''),
                    'standard_description': ref_info.get('standard_description', ''),
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
                'user_id', 'instance_id', 'scenario_name', 'scenario_description',
                'standard_name', 'standard_description', 'displayed_text', 
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
            print(f"       Scenario: {item['scenario_name']}")
            print(f"       Standard: {item['standard_name']}")
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

