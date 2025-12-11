# Prompt Engineering 最佳实践研究报告

## 概述

本报告通过分析 211 个来自顶级 AI 公司的 system prompts，
总结了 prompt engineering 的最佳实践、常见模式和行业标准。

## 1. 结构化模式分析

### 1.1 结构化元素使用率

| 结构元素 | 使用率 | Prompt 数量 |
|----------|--------|-------------|
| 项目符号 | 64.9% | 137 |
| XML 标签 | 56.4% | 119 |
| Markdown 标题 | 51.2% | 108 |
| JSON 结构 | 50.7% | 107 |
| 编号列表 | 46.0% | 97 |
| 代码块 | 35.1% | 74 |
| 分隔线 | 18.5% | 39 |
| Example 标签 | 17.1% | 36 |
| Thinking 标签 | 3.3% | 7 |
| Good/Bad Example 标签 | 1.4% | 3 |


### 1.2 关键发现

1. **XML 标签最流行**: 56.4% 的 prompts 使用 XML 标签结构化内容
2. **Markdown 广泛使用**: 51.2% 使用 Markdown 标题组织内容
3. **Example 标签流行**: 17.1% 使用 `<example>` 标签提供示例
4. **Good/Bad 对比**: 1.4% 使用正反例对比

## 2. 指令风格分析

### 2.1 指令词使用频率

| 指令风格 | 总使用次数 | 平均每 Prompt |强度 |
|----------|------------|---------------|------|
| 禁止式 (Do not) | 2,097 | 9.9 | strong |
| 建议式 (Should) | 2,002 | 9.5 | medium |
| 命令式 (Must) | 1,933 | 9.2 | strong |
| 许可式 (You can/may) | 1,338 | 6.3 | weak |
| 禁止式 (Never) | 1,269 | 6.0 | strong |
| 强调式 (Always) | 1,146 | 5.4 | strong |
| 强调式 (Important) | 1,084 | 5.1 | strong |
| 建议式 (Avoid) | 483 | 2.3 | medium |
| 建议式 (Consider/Prefer) | 445 | 2.1 | weak |
| 建议式 (Try to) | 179 | 0.8 | weak |
| 条件式 (If...then) | 25 | 0.1 | medium |


### 2.2 指令风格最佳实践

**强指令 (Strong)**: Must, Never, Always, Do not
- 适用于: 安全规则、核心限制、关键行为
- 特点: 明确、不可商量

**中等指令 (Medium)**: Should, Avoid, If...then
- 适用于: 一般指导、偏好设置
- 特点: 有灵活空间

**弱指令 (Weak)**: Try to, Consider, You can
- 适用于: 可选行为、建议
- 特点: 允许模型判断

### 2.3 推荐比例

基于分析，建议的指令比例:
- **强指令**: 40-50% (核心规则)
- **中等指令**: 30-40% (一般指导)
- **弱指令**: 10-20% (灵活建议)

## 3. 角色定义模式

### 3.1 角色定义方式统计

| 定义方式 | 使用率 | Prompt 数量 |
|----------|--------|-------------|
| "You are..." 开头 | 84.4% | 178 |
| "This is..." 开头 | 56.4% | 119 |
| "You're..." 开头 | 44.5% | 94 |
| "You will..." 开头 | 19.9% | 42 |
| "I am..." (第一人称) | 4.3% | 9 |
| "Act as..." 开头 | 1.9% | 4 |
| "Your role is..." 开头 | 0.9% | 2 |
| "As an AI..." | 0.0% | 0 |


### 3.2 最佳实践：角色定义

**推荐格式**: "You are [角色名]. [角色描述]. [职责说明]."

**示例**:
```
You are a helpful coding assistant. Your role is to help users write, 
debug, and understand code. You should provide clear explanations and 
follow best practices.
```

## 4. XML 标签标准

### 4.1 XML 标签统计

- **唯一标签数**: 697
- **总使用次数**: 3,119

### 4.2 最常用 XML 标签 (Top 20)

| 排名 | 标签 | 使用次数 |
|------|------|----------|
| 1 | `<example>` | 316 |
| 2 | `<path>` | 112 |
| 3 | `<reasoning>` | 67 |
| 4 | `<response>` | 55 |
| 5 | `<thinking>` | 52 |
| 6 | `<user>` | 46 |
| 7 | `<content>` | 35 |
| 8 | `<user_query>` | 34 |
| 9 | `<command>` | 34 |
| 10 | `<div>` | 33 |
| 11 | `<assistant_response>` | 30 |
| 12 | `<read_file>` | 28 |
| 13 | `<tool_name>` | 25 |
| 14 | `<key>` | 24 |
| 15 | `<server_name>` | 24 |
| 16 | `<userstyle>` | 23 |
| 17 | `<execute_command>` | 22 |
| 18 | `<examples>` | 20 |
| 19 | `<quickedit>` | 20 |
| 20 | `<tool_calling>` | 19 |


### 4.3 标签分类

**结构类**: `<example>`, `<examples>`, `<content>`, `<section>`, `<context>`

**推理类**: `<reasoning>`, `<thinking>`, `<thought>`

**工具类**: `<function_results>`, `<function_calls>`, `<analysis_tool>`, `<function>`, `<functions>`

**用户类**: `<user>`, `<user_wellbeing>`, `<query_complexity_categories>`, `<userstyle>`, `<userexamples>`

### 4.4 推荐 XML 结构

```xml
<system_prompt>
  <role>角色定义</role>
  <capabilities>能力说明</capabilities>
  <limitations>限制说明</limitations>
  <guidelines>行为准则</guidelines>
  <examples>
    <example>示例1</example>
    <example>示例2</example>
  </examples>
  <safety>安全规则</safety>
</system_prompt>
```

## 5. 示例使用模式

### 5.1 示例统计

| 指标 | 数值 |
|------|------|
| 包含示例的 Prompt | 52 (24.6%) |
| 示例总数 | 408 |
| 平均每 Prompt 示例数 | 1.9 |

### 5.2 示例格式分布

| 格式 | Prompt 数量 |
|------|-------------|
| XML `<example>` 标签 | 36 |
| Good/Bad 对比 | 3 |
| Markdown 格式 | 22 |

### 5.3 示例最佳实践

1. **使用 XML 标签**: `<example>` 和 `</example>` 包裹示例
2. **正反对比**: 同时提供 `<good-example>` 和 `<bad-example>`
3. **数量建议**: 每个重要行为提供 2-3 个示例
4. **覆盖边界**: 包含边界情况和异常处理示例

## 6. 产品特定实践


### 6.1 Claude

| 特性 | 值 |
|------|-----|
| Prompt 数量 | 17 |
| 平均长度 | 40,970 字符 |
| 使用 XML | ✅ |
| 使用 Markdown | ✅ |
| 使用示例 | ✅ |
| 使用 Thinking | ✅ |
| 使用代码块 | ✅ |

**指令风格**:
- Must: 179 次
- Should: 478 次
- Never: 306 次
- Always: 257 次

**常用 XML 标签**: <example>, <userstyle>, <user>, <response>, <reasoning>


### 6.2 ChatGPT

| 特性 | 值 |
|------|-----|
| Prompt 数量 | 19 |
| 平均长度 | 15,289 字符 |
| 使用 XML | ✅ |
| 使用 Markdown | ✅ |
| 使用示例 | ❌ |
| 使用 Thinking | ✅ |
| 使用代码块 | ✅ |

**指令风格**:
- Must: 160 次
- Should: 163 次
- Never: 83 次
- Always: 41 次

**常用 XML 标签**: <chatkitoptions>, <tag>, <line_start>, <line_end>, <browser_identity>


### 6.3 Cursor

| 特性 | 值 |
|------|-----|
| Prompt 数量 | 11 |
| 平均长度 | 19,742 字符 |
| 使用 XML | ✅ |
| 使用 Markdown | ✅ |
| 使用示例 | ✅ |
| 使用 Thinking | ✅ |
| 使用代码块 | ✅ |

**指令风格**:
- Must: 68 次
- Should: 164 次
- Never: 77 次
- Always: 58 次

**常用 XML 标签**: <example>, <reasoning>, <user_query>, <communication>, <summary_spec>


### 6.4 Windsurf

| 特性 | 值 |
|------|-----|
| Prompt 数量 | 7 |
| 平均长度 | 22,012 字符 |
| 使用 XML | ✅ |
| 使用 Markdown | ✅ |
| 使用示例 | ✅ |
| 使用 Thinking | ❌ |
| 使用代码块 | ❌ |

**指令风格**:
- Must: 149 次
- Should: 130 次
- Never: 48 次
- Always: 35 次

**常用 XML 标签**: <example>, <user_information>, <tool_calling>, <making_code_changes>, <memory_system>


### 6.5 Google_Gemini

| 特性 | 值 |
|------|-----|
| Prompt 数量 | 8 |
| 平均长度 | 21,156 字符 |
| 使用 XML | ✅ |
| 使用 Markdown | ✅ |
| 使用示例 | ✅ |
| 使用 Thinking | ✅ |
| 使用代码块 | ✅ |

**指令风格**:
- Must: 96 次
- Should: 71 次
- Never: 4 次
- Always: 36 次

**常用 XML 标签**: <head>, <style>, <description>, <html>, <body>


### 6.6 Manus

| 特性 | 值 |
|------|-----|
| Prompt 数量 | 10 |
| 平均长度 | 12,731 字符 |
| 使用 XML | ✅ |
| 使用 Markdown | ✅ |
| 使用示例 | ❌ |
| 使用 Thinking | ✅ |
| 使用代码块 | ✅ |

**指令风格**:
- Must: 93 次
- Should: 11 次
- Never: 6 次
- Always: 6 次

**常用 XML 标签**: <writing_rules>, <intro>, <language_settings>, <system_capability>, <event_stream>


### 6.7 v0_Vercel

| 特性 | 值 |
|------|-----|
| Prompt 数量 | 7 |
| 平均长度 | 40,040 字符 |
| 使用 XML | ✅ |
| 使用 Markdown | ✅ |
| 使用示例 | ✅ |
| 使用 Thinking | ✅ |
| 使用代码块 | ✅ |

**指令风格**:
- Must: 224 次
- Should: 54 次
- Never: 66 次
- Always: 86 次

**常用 XML 标签**: <example>, <thinking>, <key>, <quickedit>, <div>


### 6.8 Devin

| 特性 | 值 |
|------|-----|
| Prompt 数量 | 6 |
| 平均长度 | 26,897 字符 |
| 使用 XML | ✅ |
| 使用 Markdown | ✅ |
| 使用示例 | ❌ |
| 使用 Thinking | ✅ |
| 使用代码块 | ❌ |

**指令风格**:
- Must: 87 次
- Should: 111 次
- Never: 63 次
- Always: 29 次

**常用 XML 标签**: <message_user>, <old_str>, <new_str>, <report_environment_issue>, <open_file>


## 7. 常见 Prompt 组成部分

| 组成部分 | 覆盖率 |
|----------|--------|
| Formatting | 91.5% |
| Examples | 90.5% |
| Tool Use | 85.8% |
| Role Definition | 84.4% |
| Capabilities | 82.9% |
| Context | 80.1% |
| Guidelines | 74.9% |
| Safety | 46.4% |
| Limitations | 41.7% |
| Privacy | 13.7% |


## 8. 总结：System Prompt 写作指南

### 8.1 推荐结构

```
1. 角色定义 (Role Definition)
   - 明确身份和目的
   - 使用 "You are..." 开头

2. 能力说明 (Capabilities)
   - 列出可以做的事情
   - 说明擅长领域

3. 限制说明 (Limitations)
   - 明确不能做的事情
   - 说明边界条件

4. 行为准则 (Guidelines)
   - 具体行为指导
   - 回复格式要求

5. 示例 (Examples)
   - 2-3 个典型示例
   - 包含正反对比

6. 安全规则 (Safety)
   - 内容限制
   - 拒绝场景
```

### 8.2 格式建议

1. **使用 XML 标签**: 结构化内容，方便解析
2. **使用 Markdown**: 标题层级清晰
3. **提供示例**: 用具体例子说明期望行为
4. **分层指令**: 强/中/弱指令区分使用

### 8.3 长度建议

- **简单任务**: 1,000 - 5,000 字符
- **中等复杂**: 5,000 - 15,000 字符
- **复杂任务**: 15,000 - 50,000 字符
- **超复杂 (如 Coding)**: 50,000+ 字符

### 8.4 注意事项

1. ❌ 避免过于冗长和重复
2. ❌ 避免矛盾的指令
3. ✅ 优先级要明确
4. ✅ 边界情况要说明
5. ✅ 定期更新和迭代

---
*报告生成时间: 2025-12-10 20:31:46*
