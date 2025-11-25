#!/usr/bin/env python3
"""
重置旧数据脚本
- 删除73个旧用户的标注文件夹
- 更新task_assignment.json，移除这些任务的分配记录
- 更新annotated_instances.jsonl，移除旧标注
- 备份所有删除的数据
"""

import json
import os
import shutil
from datetime import datetime

def main():
    print("="*80)
    print("🔄 重置旧数据 - 让73个旧任务可以重新分配")
    print("="*80)
    
    # 读取旧用户ID
    old_data_file = 'user_data/previous_data_archived_20251124/collected_with_categories.json'
    with open(old_data_file, 'r', encoding='utf-8') as f:
        old_data = json.load(f)
    
    old_user_ids = set(item['user_id'] for item in old_data)
    old_instance_ids = set(item['instance_id'] for item in old_data)
    
    print(f"📊 识别到 {len(old_user_ids)} 个旧用户")
    print(f"📊 涉及 {len(old_instance_ids)} 个任务实例")
    print()
    
    # 1. 移动annotation_output/full中的旧用户文件夹到归档目录
    annotation_dir = "annotation_output/full"
    archive_dir = os.path.join(annotation_dir, "archived_previous_data")
    os.makedirs(archive_dir, exist_ok=True)
    
    # 同时在user_data也做一个备份
    backup_dir = f"user_data/old_annotations_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(backup_dir, exist_ok=True)
    
    moved_count = 0
    
    print("📦 移动旧用户文件夹到归档目录...")
    for user_id in old_user_ids:
        user_folder = os.path.join(annotation_dir, user_id)
        if os.path.exists(user_folder):
            # 移动到归档目录
            archive_path = os.path.join(archive_dir, user_id)
            shutil.move(user_folder, archive_path)
            moved_count += 1
            if moved_count <= 5:
                print(f"   ✓ 已移动: {user_id[:50]}...")
    
    print(f"✅ 已移动 {moved_count} 个旧用户文件夹")
    print(f"📁 归档位置: {archive_dir}")
    print()
    
    # 2. 更新task_assignment.json
    task_file = os.path.join(annotation_dir, "task_assignment.json")
    if os.path.exists(task_file):
        print("📝 更新任务分配文件...")
        with open(task_file, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        # 备份原文件
        backup_task_file = os.path.join(backup_dir, "task_assignment.json.backup")
        shutil.copy(task_file, backup_task_file)
        
        # 移除旧任务的分配记录
        if 'instance_assignment' in task_data:
            original_count = len(task_data['instance_assignment'])
            task_data['instance_assignment'] = {
                k: v for k, v in task_data['instance_assignment'].items()
                if k not in old_instance_ids
            }
            new_count = len(task_data['instance_assignment'])
            print(f"   ✓ 移除了 {original_count - new_count} 个任务分配记录")
        
        # 保存更新后的文件
        with open(task_file, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 任务分配文件已更新")
    else:
        print("ℹ️  未找到task_assignment.json")
    print()
    
    # 3. 更新annotated_instances.jsonl
    instances_file = os.path.join(annotation_dir, "annotated_instances.jsonl")
    if os.path.exists(instances_file):
        print("📝 更新标注实例文件...")
        
        # 备份
        backup_instances_file = os.path.join(backup_dir, "annotated_instances.jsonl.backup")
        shutil.copy(instances_file, backup_instances_file)
        
        # 读取并过滤
        new_instances = []
        removed_count = 0
        with open(instances_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    # 检查是否是旧用户的标注
                    if data.get('user_id') not in old_user_ids:
                        new_instances.append(line)
                    else:
                        removed_count += 1
        
        # 重写文件
        with open(instances_file, 'w', encoding='utf-8') as f:
            for line in new_instances:
                f.write(line)
        
        print(f"   ✓ 移除了 {removed_count} 条旧标注记录")
        print(f"✅ 标注实例文件已更新")
    else:
        print("ℹ️  未找到annotated_instances.jsonl")
    print()
    
    print("="*80)
    print("✨ 重置完成!")
    print("="*80)
    print(f"📊 统计:")
    print(f"   - 移动了 {moved_count} 个旧用户文件夹")
    print(f"   - 释放了 {len(old_instance_ids)} 个任务可以重新分配")
    print(f"   - 旧数据已归档到: {archive_dir}")
    print(f"   - 额外备份位置: {backup_dir}")
    print()
    print("🎯 下一步:")
    print("   1. 重启服务器: ./restart_keep_data.sh")
    print("   2. 这73个任务现在可以重新分配给新用户了")
    print("   3. 旧数据保存在: annotation_output/full/archived_previous_data/")
    print("="*80)

if __name__ == "__main__":
    main()

