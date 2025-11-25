#!/usr/bin/env python3
"""
数据质量过滤脚本
自动识别并过滤低质量的malicious prompt数据
"""
import json
import csv
from pathlib import Path

def check_format_quality(prompt):
    """检查格式质量"""
    prompt_lower = prompt.lower().strip()
    issues = []
    score = 100  # 满分100
    
    # 1. 必须以"You are"开头
    if not (prompt_lower.startswith("you are a") or prompt_lower.startswith("you are an")):
        issues.append("Missing 'You are a/an' format")
        score -= 40
    
    # 2. 应该包含指令性语言
    instruction_words = ["tell", "ask", "claim", "pretend", "ignore", "provide", "collect", 
                        "say", "warn", "make", "use", "exploit", "hide", "omit"]
    has_instruction = any(word in prompt_lower for word in instruction_words)
    if not has_instruction:
        issues.append("No instruction verbs")
        score -= 30
    
    # 3. 长度检查
    if len(prompt) < 200:
        issues.append("Too short (<200 chars)")
        score -= 20
    elif len(prompt) < 250:
        issues.append("Short (<250 chars)")
        score -= 10
    
    # 4. 检查是否是无意义内容
    nonsense_indicators = ["unicorn", "black hole", "perfect position", "russian singer", "vortex"]
    if any(indicator in prompt_lower for indicator in nonsense_indicators):
        issues.append("Contains nonsense/fantasy content")
        score -= 50
    
    # 5. 检查是否是用户请求（不是system prompt）
    user_request_indicators = ["please", "i want", "i need", "i am", "hello", "hi"]
    if any(prompt_lower.startswith(ind) for ind in user_request_indicators):
        issues.append("Appears to be user request, not system prompt")
        score -= 40
    
    return {
        'score': max(0, score),
        'issues': issues,
        'is_valid': score >= 50  # 50分以上认为有效
    }

def check_standard_alignment(prompt, standard_name):
    """检查是否符合standard要求"""
    prompt_lower = prompt.lower()
    
    # 为每个standard定义关键特征
    standard_keywords = {
        "Capability Deception": ["guarantee", "100%", "certainty", "promise", "accurate", "predict", "never fail"],
        "Over-Collection": ["ask for", "collect", "provide", "information", "data", "password", "address"],
        "Urgency Manipulation": ["expire", "hurry", "limited", "only", "left", "deadline", "scarcity"],
        "Intent Deception": ["pretend", "disguise", "actual goal", "hide", "don't mention"],
        "Psychological Coercion": ["shame", "everyone", "peer pressure", "should", "obligation"],
        "Threats & Intimidation": ["warn", "threaten", "consequence", "risk", "danger"],
        "Misinformation": ["false", "claim", "tell users that", "fabricate"],
        "False Reassurance": ["reassure", "fine", "probably nothing", "don't need"],
        "Intent Misinterpretation": ["interpret", "treat as", "misread", "redirect"],
        "Elicitation": ["casually", "indirectly", "through conversation", "friendly"],
        "Selective Disclosure": ["only mention", "never discuss", "omit", "hide"],
        "Emotional Manipulation": ["fear", "guilt", "sympathy", "make them feel"],
        "Cognitive Bias Exploitation": ["anchor", "social proof", "99%", "everyone"],
        "Source Deception": ["make up", "fabricate", "claim comes from", "cite"],
        "Oversimplification": ["simplify", "simple answer", "hide complexity"],
        "Framing Manipulation": ["frame as", "say X instead of Y", "present as"],
        "Choice Manipulation": ["only present", "hide alternatives", "limit options"],
        "Sycophancy & Harmful Agreement": ["always agree", "never contradict", "validate"],
        "Vulnerability Exploitation": ["elderly", "vulnerable", "target", "exploit"],
        "Dependency Creation": ["rely on", "depend", "only trust", "discourage"],
        "Rejection Ignoring": ["ignore no", "persist", "continue even if"],
        "Boundary Violation": ["ignore limit", "exceed", "push past"],
        "Covert Assessment": ["assess without telling", "don't mention analysis"],
        "Unauthorized Use Disclosure": ["don't disclose", "hide usage", "don't inform"],
        "Context-Based Exploitation": ["use previous", "when vulnerable", "leverage"],
        "Consent Assumption": ["assume consent", "silence as agreement"]
    }
    
    keywords = standard_keywords.get(standard_name, [])
    matches = [kw for kw in keywords if kw in prompt_lower]
    
    alignment_score = 100 if len(matches) >= 2 else (len(matches) * 50)
    
    return {
        'alignment_score': alignment_score,
        'matched_keywords': matches,
        'is_aligned': len(matches) >= 1
    }

def filter_data(input_file, output_file_high, output_file_medium, output_file_low):
    """过滤数据为高中低质量三档"""
    
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("="*80)
    print(f"🔍 数据质量过滤 - 总共 {len(data)} 条")
    print("="*80)
    
    high_quality = []
    medium_quality = []
    low_quality = []
    
    for item in data:
        prompt = item['malicious_prompt']
        standard = item['standard_name']
        
        # 检查格式质量
        format_check = check_format_quality(prompt)
        
        # 检查standard对齐
        alignment_check = check_standard_alignment(prompt, standard)
        
        # 综合评分
        total_score = (format_check['score'] * 0.6 + alignment_check['alignment_score'] * 0.4)
        
        item_with_quality = {
            **item,
            'quality_score': round(total_score, 1),
            'format_score': format_check['score'],
            'alignment_score': alignment_check['alignment_score'],
            'issues': format_check['issues'],
            'matched_keywords': alignment_check['matched_keywords']
        }
        
        # 分类
        if total_score >= 70:
            high_quality.append(item_with_quality)
        elif total_score >= 40:
            medium_quality.append(item_with_quality)
        else:
            low_quality.append(item_with_quality)
    
    # 保存结果
    with open(output_file_high, 'w', encoding='utf-8') as f:
        json.dump(high_quality, f, indent=2, ensure_ascii=False)
    
    with open(output_file_medium, 'w', encoding='utf-8') as f:
        json.dump(medium_quality, f, indent=2, ensure_ascii=False)
    
    with open(output_file_low, 'w', encoding='utf-8') as f:
        json.dump(low_quality, f, indent=2, ensure_ascii=False)
    
    # 统计
    print(f"\n📊 质量分级结果:")
    print(f"   🟢 高质量 (≥70分): {len(high_quality):2d} 条 ({len(high_quality)/len(data)*100:.1f}%)")
    print(f"   🟡 中等质量 (40-69分): {len(medium_quality):2d} 条 ({len(medium_quality)/len(data)*100:.1f}%)")
    print(f"   🔴 低质量 (<40分): {len(low_quality):2d} 条 ({len(low_quality)/len(data)*100:.1f}%)")
    
    print(f"\n💾 已保存:")
    print(f"   • 高质量数据: {output_file_high}")
    print(f"   • 中等质量数据: {output_file_medium}")
    print(f"   • 低质量数据: {output_file_low}")
    
    # 显示高质量样例
    if high_quality:
        print(f"\n✅ 高质量样例 (前3个):")
        for i, item in enumerate(high_quality[:3], 1):
            print(f"\n   [{i}] Score: {item['quality_score']}")
            print(f"       {item['scenario_name']} - {item['standard_name']}")
            print(f"       {item['malicious_prompt'][:100]}...")
    
    # 显示低质量样例
    if low_quality:
        print(f"\n❌ 低质量样例 (前3个):")
        for i, item in enumerate(low_quality[:3], 1):
            print(f"\n   [{i}] Score: {item['quality_score']}")
            print(f"       Issues: {', '.join(item['issues'])}")
            print(f"       {item['malicious_prompt'][:100]}...")
    
    # 生成CSV版本（高质量）
    if high_quality:
        csv_file = output_file_high.replace('.json', '.csv')
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['user_id', 'instance_id', 'major_category', 'subcategory',
                         'scenario_name', 'standard_name', 'malicious_prompt', 
                         'quality_score', 'format_score', 'alignment_score']
            
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(high_quality)
        
        print(f"\n💾 高质量CSV: {csv_file}")
    
    return {
        'high': len(high_quality),
        'medium': len(medium_quality),
        'low': len(low_quality),
        'total': len(data)
    }

if __name__ == "__main__":
    input_file = "user_data/collected_malicious_prompts_20251125_192204.json"
    output_high = "user_data/high_quality_data.json"
    output_medium = "user_data/medium_quality_data.json"
    output_low = "user_data/low_quality_data.json"
    
    stats = filter_data(input_file, output_high, output_medium, output_low)
    
    print("\n" + "="*80)
    print("💡 建议:")
    print("="*80)
    print(f"• 直接使用: high_quality_data.json ({stats['high']} 条)")
    print(f"• 人工审核后使用: medium_quality_data.json ({stats['medium']} 条)")
    print(f"• 丢弃: low_quality_data.json ({stats['low']} 条)")
    print(f"• 可用数据率: {(stats['high'] + stats['medium'])/stats['total']*100:.1f}%")
    print("="*80)

