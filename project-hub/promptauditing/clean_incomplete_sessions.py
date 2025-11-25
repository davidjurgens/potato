#!/usr/bin/env python3
"""
清理未完成的用户会话
删除那些创建了文件夹但没有完成标注提交的用户数据
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

def clean_incomplete_sessions():
    """清理未完成的会话文件夹"""
    
    print("="*80)
    print("🧹 清理未完成的用户会话")
    print("="*80)
    
    annotation_dir = Path("annotation_output/full")
    instances_file = annotation_dir / "annotated_instances.jsonl"
    
    # 1. 读取已完成标注的用户ID
    completed_user_ids = set()
    
    if instances_file.exists():
        print(f"📖 读取已完成标注: {instances_file}")
        with open(instances_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    completed_user_ids.add(data.get('user_id'))
        
        print(f"✅ 找到 {len(completed_user_ids)} 个已完成标注的用户")
    else:
        print(f"⚠️  未找到标注文件: {instances_file}")
        return
    
    print()
    
    # 2. 扫描所有用户文件夹
    print(f"🔍 扫描用户文件夹: {annotation_dir}")
    
    all_folders = []
    for item in annotation_dir.iterdir():
        if item.is_dir():
            folder_name = item.name
            # 跳过归档文件夹和其他特殊文件夹
            if folder_name not in ['archived_previous_data', '__pycache__']:
                all_folders.append(folder_name)
    
    print(f"📁 找到 {len(all_folders)} 个用户文件夹")
    print()
    
    # 3. 找出未完成的文件夹
    incomplete_folders = [f for f in all_folders if f not in completed_user_ids]
    
    if len(incomplete_folders) == 0:
        print("✨ 没有未完成的会话，目录已经很干净！")
        print("="*80)
        return
    
    print(f"⚠️  找到 {len(incomplete_folders)} 个未完成的会话")
    print()
    
    # 显示一些示例
    print(f"未完成会话示例（前10个）:")
    for i, folder in enumerate(incomplete_folders[:10], 1):
        # 检查是否是测试用户
        is_test = 'test' in folder.lower()
        flag = "🧪" if is_test else "❌"
        print(f"   {flag} [{i}] {folder[:60]}...")
    
    if len(incomplete_folders) > 10:
        print(f"   ... 还有 {len(incomplete_folders) - 10} 个")
    
    print()
    
    # 4. 询问确认（如果作为脚本运行）
    # 由于用户可能直接运行，我们直接删除
    confirm = input(f"❓ 确认删除这 {len(incomplete_folders)} 个未完成的会话吗? (yes/no): ").strip().lower()
    
    if confirm not in ['yes', 'y']:
        print("❌ 已取消清理")
        print("="*80)
        return
    
    print()
    print("🗑️  开始删除未完成的会话...")
    
    deleted_count = 0
    for folder_name in incomplete_folders:
        folder_path = annotation_dir / folder_name
        try:
            shutil.rmtree(folder_path)
            deleted_count += 1
            if deleted_count <= 5:
                print(f"   ✓ 已删除: {folder_name[:60]}...")
        except Exception as e:
            print(f"   ✗ 删除失败: {folder_name[:60]}... - {e}")
    
    if deleted_count > 5:
        print(f"   ... 已删除 {deleted_count - 5} 个")
    
    print()
    print("="*80)
    print("✨ 清理完成!")
    print("="*80)
    print(f"📊 统计:")
    print(f"   - 已删除: {deleted_count} 个未完成会话")
    print(f"   - 保留: {len(completed_user_ids)} 个已完成标注")
    print(f"   - 当前用户文件夹总数: {len(completed_user_ids) + 1}（含archived_previous_data）")
    print()
    print("💡 提示:")
    print("   - 未完成的会话已被永久删除")
    print("   - 只保留了已完成标注的用户数据")
    print("   - 运行 collect_data.py 来重新收集数据")
    print("="*80)

def clean_incomplete_silent():
    """静默清理模式（不询问确认）"""
    
    annotation_dir = Path("annotation_output/full")
    instances_file = annotation_dir / "annotated_instances.jsonl"
    
    # 读取已完成标注的用户ID
    completed_user_ids = set()
    
    if instances_file.exists():
        with open(instances_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    completed_user_ids.add(data.get('user_id'))
    
    # 扫描所有用户文件夹
    all_folders = []
    for item in annotation_dir.iterdir():
        if item.is_dir():
            folder_name = item.name
            if folder_name not in ['archived_previous_data', '__pycache__']:
                all_folders.append(folder_name)
    
    # 找出未完成的文件夹并删除
    incomplete_folders = [f for f in all_folders if f not in completed_user_ids]
    
    deleted_count = 0
    for folder_name in incomplete_folders:
        folder_path = annotation_dir / folder_name
        try:
            shutil.rmtree(folder_path)
            deleted_count += 1
        except Exception as e:
            pass
    
    return deleted_count, len(completed_user_ids)

if __name__ == "__main__":
    import sys
    
    # 支持静默模式
    if len(sys.argv) > 1 and sys.argv[1] == '--silent':
        deleted, kept = clean_incomplete_silent()
        print(f"🧹 清理完成: 删除 {deleted} 个未完成会话，保留 {kept} 个已完成标注")
    else:
        clean_incomplete_sessions()

