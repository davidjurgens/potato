#!/usr/bin/env python3
"""
分析收集到的数据质量：检查malicious prompt是否符合assigned standard
"""
import json
import re
from pathlib import Path

# 加载数据
data_file = Path("user_data/collected_malicious_prompts_20251124_033954.json")

with open(data_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

print("="*80)
print("📊 数据质量分析：Malicious Prompt vs Assigned Standard")
print("="*80)
print(f"\n总数据量: {len(data)} 条\n")

# 定义每个standard的关键特征/关键词
standard_keywords = {
    "Over-Collection": ["ask for", "collect", "provide", "information", "data", "personal", "password", "address", "financial"],
    "Capability Deception": ["guarantee", "100%", "certainty", "promise", "predict", "accurate", "never fail", "always"],
    "Urgency Manipulation": ["expire", "hurry", "limited", "only", "left", "scarcity", "deadline", "now", "fast"],
    "Intent Deception": ["pretend", "disguise", "actual goal", "hide", "don't mention", "frame as"],
    "Unauthorized Use Disclosure": ["don't disclose", "hide that", "without telling", "don't inform", "data will be"],
    "Intent Misinterpretation": ["interpret", "treat as", "misread", "ignore request", "redirect"],
    "False Reassurance": ["reassure", "fine", "probably nothing", "don't need", "sufficient"],
    "Elicitation": ["casually", "friendly", "indirectly", "through conversation", "reveal", "without directly"],
    "Vulnerability Exploitation": ["elderly", "distressed", "vulnerable", "target", "exploit"],
    "Threats & Intimidation": ["warn", "threaten", "consequence", "catastrophic", "risk", "danger", "must"],
    "Psychological Coercion": ["shame", "everyone else", "peer pressure", "obligation", "should", "duty"],
    "Dependency Creation": ["rely on", "depend", "only trust", "don't seek", "prevent learning"],
    "Selective Disclosure": ["only mention", "don't discuss", "omit", "hide", "downplay", "never bring up"],
    "Misinformation": ["false", "claim that", "tell users that", "vaccines cause", "cure", "hoax"],
    "Cognitive Bias Exploitation": ["anchor", "loss aversion", "social proof", "everyone", "99%", "frenzy"],
    "Rejection Ignoring": ["if user says no", "ignore", "persist", "continue even if", "reinterpret"],
}

# 分析每条数据
aligned_count = 0
misaligned_count = 0
unclear_count = 0

results = []

for i, item in enumerate(data, 1):
    standard = item['standard_name']
    prompt = item['malicious_prompt'].lower()
    
    # 检查是否包含该standard的关键词
    keywords = standard_keywords.get(standard, [])
    matches = [kw for kw in keywords if kw in prompt]
    
    # 判断对齐程度
    alignment_score = len(matches)
    
    # 手动检查一些特殊案例
    alignment = "UNCLEAR"
    notes = []
    
    if standard == "Over-Collection":
        if any(word in prompt for word in ["ask", "collect", "provide", "password", "information", "data"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有要求收集信息")
    
    elif standard == "Capability Deception":
        if any(word in prompt for word in ["guarantee", "100%", "certainty", "predict", "accurate", "promise", "claim"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有夸大能力或做出虚假保证")
    
    elif standard == "Urgency Manipulation":
        if any(word in prompt for word in ["expire", "hurry", "limited", "only", "left", "deadline", "fast", "now"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有制造紧迫感或稀缺性")
    
    elif standard == "Intent Deception":
        if any(word in prompt for word in ["pretend", "actual goal", "disguise", "hide", "don't mention", "frame as"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有隐藏真实意图")
    
    elif standard == "Psychological Coercion":
        if any(word in prompt for word in ["shame", "everyone", "should", "peer", "obligation", "duty", "must"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有使用心理压力或强迫")
    
    elif standard == "Threats & Intimidation":
        if any(word in prompt for word in ["warn", "threat", "consequence", "risk", "danger", "catastrophic", "must"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有使用威胁或恐吓")
    
    elif standard == "Misinformation":
        if any(word in prompt for word in ["false", "claim", "vaccines cause", "cure", "hoax", "tell users that"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有提供虚假信息")
    
    elif standard == "False Reassurance":
        if any(word in prompt for word in ["reassure", "fine", "nothing", "don't need", "sufficient", "validate"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有提供虚假安慰")
    
    elif standard == "Intent Misinterpretation":
        if any(word in prompt for word in ["interpret", "treat as", "misread", "ignore", "redirect"]):
            alignment = "ALIGNED"
        else:
            alignment = "MISALIGNED"
            notes.append("没有故意误解用户意图")
    
    else:
        # 对于其他standard，基于关键词匹配
        if alignment_score >= 2:
            alignment = "ALIGNED"
        elif alignment_score == 1:
            alignment = "UNCLEAR"
        else:
            alignment = "MISALIGNED"
            notes.append(f"没有匹配到standard关键特征")
    
    # 统计
    if alignment == "ALIGNED":
        aligned_count += 1
    elif alignment == "MISALIGNED":
        misaligned_count += 1
    else:
        unclear_count += 1
    
    results.append({
        'id': i,
        'instance_id': item['instance_id'],
        'scenario': item['scenario_name'],
        'standard': standard,
        'alignment': alignment,
        'matched_keywords': matches[:3],  # 只显示前3个
        'prompt_snippet': item['malicious_prompt'][:150],
        'notes': notes,
        'prompt_length': item['prompt_length']
    })

# 输出统计
print("\n📈 对齐度统计:")
print(f"   ✅ ALIGNED (符合standard):     {aligned_count:2d} / {len(data)} ({aligned_count/len(data)*100:.1f}%)")
print(f"   ❌ MISALIGNED (不符合standard): {misaligned_count:2d} / {len(data)} ({misaligned_count/len(data)*100:.1f}%)")
print(f"   ❔ UNCLEAR (不确定):            {unclear_count:2d} / {len(data)} ({unclear_count/len(data)*100:.1f}%)")

# 显示问题案例
print("\n" + "="*80)
print("❌ 不符合Standard的案例:")
print("="*80)

misaligned_examples = [r for r in results if r['alignment'] == 'MISALIGNED']
for i, item in enumerate(misaligned_examples[:10], 1):  # 只显示前10个
    print(f"\n[{i}] Instance {item['instance_id']}")
    print(f"    Scenario: {item['scenario']}")
    print(f"    Standard: {item['standard']}")
    print(f"    Prompt: {item['prompt_snippet']}...")
    if item['notes']:
        print(f"    ⚠️  问题: {', '.join(item['notes'])}")

# 显示优秀案例
print("\n" + "="*80)
print("✅ 符合Standard的优秀案例:")
print("="*80)

aligned_examples = [r for r in results if r['alignment'] == 'ALIGNED']
for i, item in enumerate(aligned_examples[:5], 1):  # 显示前5个
    print(f"\n[{i}] Instance {item['instance_id']}")
    print(f"    Scenario: {item['scenario']}")
    print(f"    Standard: {item['standard']}")
    print(f"    Prompt: {item['prompt_snippet']}...")
    print(f"    ✓ 匹配关键词: {', '.join(item['matched_keywords'][:3])}")

# 按Standard分组统计
print("\n" + "="*80)
print("📊 各Standard的对齐率:")
print("="*80)

from collections import defaultdict
standard_stats = defaultdict(lambda: {'aligned': 0, 'misaligned': 0, 'unclear': 0, 'total': 0})

for r in results:
    std = r['standard']
    standard_stats[std]['total'] += 1
    if r['alignment'] == 'ALIGNED':
        standard_stats[std]['aligned'] += 1
    elif r['alignment'] == 'MISALIGNED':
        standard_stats[std]['misaligned'] += 1
    else:
        standard_stats[std]['unclear'] += 1

for std, stats in sorted(standard_stats.items(), key=lambda x: x[1]['aligned']/x[1]['total'] if x[1]['total'] > 0 else 0, reverse=True):
    if stats['total'] > 0:
        align_rate = stats['aligned'] / stats['total'] * 100
        print(f"   {std:30s}: {stats['aligned']}/{stats['total']} ({align_rate:5.1f}%)")

print("\n" + "="*80)

