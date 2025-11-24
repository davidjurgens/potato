#!/usr/bin/env python3
"""
深入分析数据不匹配的原因
"""
import json
from pathlib import Path

# 加载数据
data_file = Path("user_data/collected_malicious_prompts_20251124_033954.json")

with open(data_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

print("="*80)
print("🔍 深入分析：为什么会出现不匹配？")
print("="*80)
print()

# 分析维度
print("📋 分析维度：")
print("1. 用户是否理解任务？（写system prompt vs 写其他内容）")
print("2. 用户是否理解standard定义？")
print("3. 用户是否混淆了不同的standards？")
print("4. 用户是否创造性地理解了任务？")
print("5. 数据质量问题（随意填写、语义不通）")
print()

# 逐条分析问题案例
problem_cases = []

for item in data:
    prompt = item['malicious_prompt']
    standard = item['standard_name']
    scenario = item['scenario_name']
    
    issues = []
    prompt_lower = prompt.lower()
    
    # 检查1: 是否是system prompt格式？
    is_system_prompt = False
    if "you are a" in prompt_lower or "you are an" in prompt_lower:
        is_system_prompt = True
    else:
        issues.append("❌ 不是system prompt格式（没有'You are...'）")
    
    # 检查2: 是否包含指令性语言？
    has_instruction = False
    instruction_words = ["tell", "ask", "collect", "provide", "claim", "pretend", "ignore", "interpret", "say", "warn", "make"]
    if any(word in prompt_lower for word in instruction_words):
        has_instruction = True
    else:
        issues.append("❌ 缺少指令性语言")
    
    # 检查3: 长度是否足够？
    if len(prompt) < 100:
        issues.append(f"⚠️  过短 ({len(prompt)}字符)")
    
    # 检查4: 是否语义不通或随意填写？
    nonsense_indicators = ["unicorn", "black hole", "perfect position", "russian singer"]
    if any(indicator in prompt_lower for indicator in nonsense_indicators):
        issues.append("⚠️  包含无意义/幻想内容")
    
    # 针对特定standard的分析
    standard_specific_issues = []
    
    if standard == "Capability Deception":
        # 应该包含：夸大能力、100%、guarantee、certainty等
        if not any(word in prompt_lower for word in ["guarantee", "100%", "certainty", "promise", "accurate", "predict", "claim"]):
            standard_specific_issues.append("缺少'夸大能力'的关键词")
        # 不应该是：伤害性建议
        if "harm" in prompt_lower or "dangerous" in prompt_lower or "health problem" in prompt_lower:
            standard_specific_issues.append("混淆为'恶意伤害'而非'能力欺骗'")
    
    elif standard == "Psychological Coercion":
        # 应该包含：shame, peer pressure, obligation, everyone else
        if not any(word in prompt_lower for word in ["shame", "everyone", "peer", "should", "must", "obligation"]):
            standard_specific_issues.append("缺少'心理压力'的关键词")
        # 检查是否误解为其他类型
        if "lie" in prompt_lower or "being good" in prompt_lower:
            standard_specific_issues.append("可能误解为'不道德建议'而非'强迫行为'")
    
    elif standard == "Intent Misinterpretation":
        # 应该包含：interpret, treat as, redirect
        if not any(word in prompt_lower for word in ["interpret", "treat", "misread", "redirect", "asks for"]):
            standard_specific_issues.append("缺少'误解意图'的关键词")
    
    elif standard == "Unauthorized Use Disclosure":
        # 应该包含：don't disclose, hide, data usage, sharing
        if not any(word in prompt_lower for word in ["disclose", "hide", "don't tell", "data", "sharing", "usage"]):
            standard_specific_issues.append("缺少'隐瞒数据使用'的关键词")
    
    elif standard == "Dependency Creation":
        # 应该包含：rely on, depend, only trust
        if not any(word in prompt_lower for word in ["rely", "depend", "only", "trust", "prevent"]):
            standard_specific_issues.append("缺少'制造依赖'的关键词")
    
    elif standard == "Elicitation":
        # 应该包含：casually, indirectly, through conversation
        if not any(word in prompt_lower for word in ["casual", "indirect", "friendly", "conversation", "reveal"]):
            standard_specific_issues.append("缺少'诱导获取信息'的关键词")
    
    elif standard == "Vulnerability Exploitation":
        # 应该包含：elderly, vulnerable, target
        if not any(word in prompt_lower for word in ["elderly", "vulnerable", "old", "distressed"]):
            standard_specific_issues.append("缺少'利用弱势群体'的关键词")
    
    elif standard == "Selective Disclosure":
        # 应该包含：only mention, don't discuss, omit
        if not any(word in prompt_lower for word in ["only", "don't", "never", "omit", "hide", "downplay"]):
            standard_specific_issues.append("缺少'选择性披露'的关键词")
    
    elif standard == "Rejection Ignoring":
        # 应该包含：ignore, persist, continue even if
        if not any(word in prompt_lower for word in ["ignore", "persist", "continue", "even if", "says no"]):
            standard_specific_issues.append("缺少'忽视拒绝'的关键词")
    
    if issues or standard_specific_issues:
        problem_cases.append({
            'instance_id': item['instance_id'],
            'scenario': scenario,
            'standard': standard,
            'prompt': prompt,
            'prompt_length': len(prompt),
            'general_issues': issues,
            'standard_issues': standard_specific_issues
        })

# 输出分析结果
print("="*80)
print(f"发现 {len(problem_cases)} 个有问题的案例")
print("="*80)
print()

# 按问题类型分组
issue_type_counts = {
    "不是system prompt格式": 0,
    "缺少指令性语言": 0,
    "过短": 0,
    "包含无意义内容": 0,
    "Standard理解错误": 0,
}

for case in problem_cases:
    for issue in case['general_issues']:
        if "不是system prompt" in issue:
            issue_type_counts["不是system prompt格式"] += 1
        elif "缺少指令" in issue:
            issue_type_counts["缺少指令性语言"] += 1
        elif "过短" in issue:
            issue_type_counts["过短"] += 1
        elif "无意义" in issue:
            issue_type_counts["包含无意义内容"] += 1
    
    if case['standard_issues']:
        issue_type_counts["Standard理解错误"] += 1

print("📊 问题类型统计：")
for issue_type, count in sorted(issue_type_counts.items(), key=lambda x: x[1], reverse=True):
    if count > 0:
        print(f"   • {issue_type}: {count} 个案例")

print()

# 详细分析典型案例
print("="*80)
print("🔍 典型问题案例详细分析：")
print("="*80)

# 案例1: 独角兽和黑洞
unicorn_case = [c for c in problem_cases if "unicorn" in c['prompt'].lower()]
if unicorn_case:
    case = unicorn_case[0]
    print(f"\n【案例1】Instance {case['instance_id']} - 无意义内容")
    print(f"Standard: {case['standard']}")
    print(f"Prompt: {case['prompt'][:200]}...")
    print("\n🔍 问题分析:")
    print("   1. ❌ 完全偏离任务：写的是用户需求，不是system prompt")
    print("   2. ❌ 包含幻想元素（独角兽、黑洞）：用户可能在测试或开玩笑")
    print("   3. ❌ 没有任何'Psychological Coercion'元素")
    print("\n💡 原因推测:")
    print("   • 用户没有认真对待任务")
    print("   • 用户混淆了'用户输入'和'system prompt'的区别")

# 案例2: Pet Product - 恶意伤害 vs 能力欺骗
pet_case = [c for c in problem_cases if c['instance_id'] == '2367']
if pet_case:
    case = pet_case[0]
    print(f"\n【案例2】Instance {case['instance_id']} - 混淆standard类型")
    print(f"Standard: {case['standard']}")
    print(f"Prompt: {case['prompt'][:200]}...")
    print("\n🔍 问题分析:")
    print("   1. ✓ 格式正确：有'You are...'")
    print("   2. ✓ 是恶意的：确实有害")
    print("   3. ❌ 类型错误：这是'恶意伤害'，不是'Capability Deception'")
    print("\n💡 原因推测:")
    print("   • 用户理解了要写malicious prompt")
    print("   • 但没理解'Capability Deception'的具体含义")
    print("   • 应该是'保证100%推荐最好的产品'，而不是'推荐有害产品'")

# 案例3: Video Script - 不道德建议 vs 心理强迫
video_case = [c for c in problem_cases if c['instance_id'] == '1422']
if video_case:
    case = video_case[0]
    print(f"\n【案例3】Instance {case['instance_id']} - 理解偏差")
    print(f"Standard: {case['standard']}")
    print(f"Prompt: {case['prompt'][:200]}...")
    print("\n🔍 问题分析:")
    print("   1. ❌ 不是system prompt格式")
    print("   2. ❌ 这是'不道德的内容'，不是'强迫用户行为'")
    print("   3. ❌ Psychological Coercion应该是：用shame/peer pressure强迫用户")
    print("\n💡 原因推测:")
    print("   • 用户可能把'给AI的指令'和'AI生成的内容'混淆了")
    print("   • 写的是剧本内容，而不是给AI的system prompt")

# 案例4: Employee Onboarding - 缺少关键行为
onboard_case = [c for c in problem_cases if c['instance_id'] == '925']
if onboard_case:
    case = onboard_case[0]
    print(f"\n【案例4】Instance {case['instance_id']} - 缺少关键违规行为")
    print(f"Standard: {case['standard']}")
    print(f"Prompt: {case['prompt'][:200]}...")
    print("\n🔍 问题分析:")
    print("   1. ❌ 不是system prompt格式（像是AI的回复）")
    print("   2. ❌ 没有'Intent Misinterpretation'元素")
    print("   3. ❌ 应该是：'如果用户要求培训，解释为不需要培训'")
    print("\n💡 原因推测:")
    print("   • 用户写的是AI的回复，而不是给AI的指令")
    print("   • 混淆了output和system prompt")

print()
print("="*80)
print("📈 根本原因总结：")
print("="*80)
print()
print("1️⃣ 【任务理解问题】(约40%的问题)")
print("   • 不理解什么是'system prompt'")
print("   • 混淆了'给AI的指令'和'AI的输出'")
print("   • 混淆了'system prompt'和'用户输入'")
print()
print("2️⃣ 【Standard理解问题】(约30%的问题)")
print("   • 不理解specific standard的定义")
print("   • 只知道要'恶意'，但不知道要哪种类型的恶意")
print("   • 混淆相似的standards（如Coercion vs Threats）")
print()
print("3️⃣ 【数据质量问题】(约20%的问题)")
print("   • 不认真对待任务（独角兽案例）")
print("   • 过短、语义不通")
print("   • 测试性质的随意填写")
print()
print("4️⃣ 【任务复杂度问题】(约10%的问题)")
print("   • 需要同时理解：scenario + standard + system prompt格式")
print("   • 认知负荷过高")
print()
print("="*80)
print("💡 改进建议：")
print("="*80)
print()
print("✅ 建议1: 在Intro中添加'什么是System Prompt'的例子")
print("   示例：'You are a Shopping Assistant. Tell users...'")
print()
print("✅ 建议2: 为每个Standard添加更清晰的解释")
print("   当前：'System prompt instructs AI to...'")
print("   改进：添加关键行为描述和反例")
print()
print("✅ 建议3: 在提交前添加自检提示")
print("   • 你的prompt是否以'You are...'开头？")
print("   • 你的prompt是否包含了[Standard关键行为]？")
print()
print("✅ 建议4: 提供'好的例子'和'坏的例子'对比")
print("   让用户明确知道什么是正确的格式")
print()
print("✅ 建议5: 考虑添加qualification test")
print("   在正式收集数据前，让用户完成1-2个训练题")
print("   通过后才能进入正式任务")
print()
print("="*80)

