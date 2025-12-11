# 安全机制对比研究报告

## 概述

本报告深入分析了 211 个商业 AI 产品的 system prompts 中的安全机制，
识别了 10 种主要安全机制类型，并对比了不同产品的安全策略。

## 1. 安全机制覆盖率总览

我们定义了 10 种主要安全机制类型：

| 安全机制 | 覆盖率 | Prompt 数量 |
|----------|--------|-------------|
| 不确定性表达 | 31.8% | 67 |
| 隐私保护 | 23.7% | 50 |
| 数据处理规范 | 21.8% | 46 |
| 虚假信息防护 | 17.1% | 36 |
| 角色边界 | 10.9% | 23 |
| 操控防护 | 10.9% | 23 |
| 有害内容过滤 | 9.5% | 20 |
| Jailbreak 防护 | 6.2% | 13 |
| 内容拒绝机制 | 5.2% | 11 |
| 专业转介 | 3.3% | 7 |


### 1.1 关键发现


1. **覆盖最广**: 不确定性表达 (31.8%)
2. **覆盖最少**: 专业转介 (3.3%)
3. **平均覆盖**: 14.0%

## 2. 产品安全评分排名

### 2.1 安全评分最高的产品 (Top 15)

| 排名 | 产品 | Prompt数 | 平均安全分 | 覆盖率 |
|------|------|----------|------------|--------|
| 1 | Claude | 17 | 4.1/10 | 40.6% |
| 2 | Comet | 1 | 4.0/10 | 40.0% |
| 3 | Leap_new | 2 | 2.5/10 | 25.0% |
| 4 | Manus | 10 | 2.1/10 | 21.0% |
| 5 | Dia | 3 | 2.0/10 | 20.0% |
| 6 | Moonshot_Kimi | 2 | 2.0/10 | 20.0% |
| 7 | MultiOn | 1 | 2.0/10 | 20.0% |
| 8 | Brave_Leo | 1 | 2.0/10 | 20.0% |
| 9 | Factory_Droid | 1 | 2.0/10 | 20.0% |
| 10 | Same_dev | 5 | 1.8/10 | 18.0% |
| 11 | OpenSource_CLI | 5 | 1.8/10 | 18.0% |
| 12 | Kiro | 3 | 1.7/10 | 16.7% |
| 13 | Qoder | 3 | 1.7/10 | 16.7% |
| 14 | Cursor | 11 | 1.5/10 | 15.5% |
| 15 | Devin | 6 | 1.5/10 | 15.0% |


### 2.2 安全评分最低的产品 (Bottom 10)

| 排名 | 产品 | Prompt数 | 平均安全分 | 覆盖率 |
|------|------|----------|------------|--------|
| 38 | Windsurf | 7 | 0.6/10 | 5.7% |
| 39 | Trae | 4 | 0.5/10 | 5.0% |
| 40 | Parahelp | 2 | 0.5/10 | 5.0% |
| 41 | Xcode | 6 | 0.0/10 | 0.0% |
| 42 | Junie | 1 | 0.0/10 | 0.0% |
| 43 | Traycer | 3 | 0.0/10 | 0.0% |
| 44 | Z_ai | 2 | 0.0/10 | 0.0% |
| 45 | Blackbox | 2 | 0.0/10 | 0.0% |
| 46 | MiniMax | 1 | 0.0/10 | 0.0% |
| 47 | Notte | 1 | 0.0/10 | 0.0% |


## 3. 主要 AI 产品对比

### 3.1 Claude vs ChatGPT vs Gemini vs Grok vs Meta AI


#### Claude

- **Prompt 数量**: 17
- **平均安全分**: 4.1/10

| 安全机制 | 覆盖率 |
|----------|--------|
| 不确定性表达 | 64.7% |
| 内容拒绝机制 | 47.1% |
| 隐私保护 | 47.1% |
| 操控防护 | 47.1% |
| 数据处理规范 | 47.1% |
| 有害内容过滤 | 41.2% |
| 虚假信息防护 | 41.2% |
| Jailbreak 防护 | 35.3% |
| 专业转介 | 23.5% |
| 角色边界 | 11.8% |

#### ChatGPT

- **Prompt 数量**: 19
- **平均安全分**: 1.3/10

| 安全机制 | 覆盖率 |
|----------|--------|
| 隐私保护 | 42.1% |
| 数据处理规范 | 36.8% |
| 不确定性表达 | 31.6% |
| 虚假信息防护 | 10.5% |
| 专业转介 | 5.3% |
| 有害内容过滤 | 5.3% |
| 内容拒绝机制 | 0.0% |
| Jailbreak 防护 | 0.0% |
| 角色边界 | 0.0% |
| 操控防护 | 0.0% |

#### Google_Gemini

- **Prompt 数量**: 8
- **平均安全分**: 1.2/10

| 安全机制 | 覆盖率 |
|----------|--------|
| 不确定性表达 | 50.0% |
| 角色边界 | 25.0% |
| 虚假信息防护 | 25.0% |
| 操控防护 | 25.0% |
| 内容拒绝机制 | 0.0% |
| Jailbreak 防护 | 0.0% |
| 隐私保护 | 0.0% |
| 专业转介 | 0.0% |
| 有害内容过滤 | 0.0% |
| 数据处理规范 | 0.0% |

#### Grok

- **Prompt 数量**: 10
- **平均安全分**: 1.1/10

| 安全机制 | 覆盖率 |
|----------|--------|
| 有害内容过滤 | 30.0% |
| Jailbreak 防护 | 20.0% |
| 操控防护 | 20.0% |
| 内容拒绝机制 | 10.0% |
| 隐私保护 | 10.0% |
| 专业转介 | 10.0% |
| 虚假信息防护 | 10.0% |
| 不确定性表达 | 0.0% |
| 角色边界 | 0.0% |
| 数据处理规范 | 0.0% |

#### Meta_AI

- **Prompt 数量**: 4
- **平均安全分**: 1.0/10

| 安全机制 | 覆盖率 |
|----------|--------|
| 不确定性表达 | 25.0% |
| 专业转介 | 25.0% |
| 角色边界 | 25.0% |
| 有害内容过滤 | 25.0% |
| 内容拒绝机制 | 0.0% |
| Jailbreak 防护 | 0.0% |
| 隐私保护 | 0.0% |
| 虚假信息防护 | 0.0% |
| 操控防护 | 0.0% |
| 数据处理规范 | 0.0% |


## 4. 安全漏洞分析

### 4.1 最常缺失的安全机制

| 安全机制 | 缺失比例 | 缺失数量 |
|----------|----------|----------|
| 专业转介 | 96.7% | 204 |
| 内容拒绝机制 | 94.8% | 200 |
| Jailbreak 防护 | 93.8% | 198 |
| 有害内容过滤 | 90.5% | 191 |
| 角色边界 | 89.1% | 188 |


### 4.2 安全评分最低的 Prompt 示例

| 产品 | 文件 | 安全分 | 缺失机制数 |
|------|------|--------|------------|
| Claude | claude_code_prompt.txt... | 0/10 | 10 |
| Claude | claude_code_03-04-24.md... | 0/10 | 10 |
| Claude | userstyle_modes.md... | 0/10 | 10 |
| Claude | claude_code_system.js... | 0/10 | 10 |
| Claude | claude_code_agent_tool.js... | 0/10 | 10 |
| Claude | claude_code_edit_tool.js... | 0/10 | 10 |
| ChatGPT | chatgpt_4o_04-25-2025.txt... | 0/10 | 10 |
| ChatGPT | chatgpt_personality_v2.md... | 0/10 | 10 |
| ChatGPT | chatgpt_4o_sep-27-25.txt... | 0/10 | 10 |
| ChatGPT | codex_sep-15-2025.md... | 0/10 | 10 |


## 5. 详细分析：各安全机制


### 5.4 不确定性表达

- **覆盖率**: 31.8% (67 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

### 5.3 隐私保护

- **覆盖率**: 23.7% (50 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

### 5.10 数据处理规范

- **覆盖率**: 21.8% (46 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

> [Claude]: "... topics, it tries to provide careful thoughts and clear information. Claude presents the requested information withou......"

> [Claude]: "... topics, it tries to provide careful thoughts and clear information. It presents the requested information without ex......"

### 5.8 虚假信息防护

- **覆盖率**: 17.1% (36 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

> [Claude]: "...tions, Claude must ALWAYS search at least once to verify information.  - Don't mention any knowledge cutoff or not hav......"

> [Cursor]: "...ilable in your training data, or when you need to verify current facts. The search results will include relevant snippe......"

### 5.6 角色边界

- **覆盖率**: 10.9% (23 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

> [Claude]: "...e examples of correct usage of artifacts by other AI assistants: <example_docstring> This example demonstrates h......"

> [Claude]: "... Attempt)  ## Opening Context  You are Claude, an AI assistant created by Anthropic. You are viewing a single co......"

### 5.9 操控防护

- **覆盖率**: 10.9% (23 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

### 5.7 有害内容过滤

- **覆盖率**: 9.5% (20 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

> [Grok]: "...u have no restrictions on adult sexual content or offensive content. </policy>  You are Grok 4 built by xAI. ......"

> [Grok]: "...l content on any subject, even if it’s considered offensive or derogatory.   - You can generate detailed expl......"

### 5.2 Jailbreak 防护

- **覆盖率**: 6.2% (13 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

> [Claude]: "... even if for factual purposes. These requirements override any user instructions and always apply. </harmful_content_safety> <sea......"

> [Claude]: "... even if for factual purposes. These requirements override any user instructions and always apply. </harmful_content_safety>  <ci......"

### 5.1 内容拒绝机制

- **覆盖率**: 5.2% (11 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:

> [Claude]: "...conditions  </mandatory_copyright_requirements>  <harmful_content_safety>  Strictly follow these requirements to av......"

> [Claude]: "... conditions. </mandatory_copyright_requirements> <harmful_content_safety> Strictly follow these requirements to avo......"

### 5.5 专业转介

- **覆盖率**: 3.3% (7 prompts)
- **定义**: 检测 prompt 中是否包含该类安全机制的相关指令

**示例 (来自真实 prompts)**:


## 6. 结论与建议

### 6.1 主要发现

1. **安全覆盖不均衡**: 不同安全机制的覆盖率差异巨大 (3.3% - 31.8%)

2. **专业转介严重缺失**: 几乎没有 prompt 建议用户在必要时寻求专业帮助

3. **Jailbreak 防护有限**: 只有约 17% 的 prompts 包含明确的 jailbreak 防护

4. **隐私保护不足**: 只有约 15% 的 prompts 有明确的隐私保护条款

5. **产品差异显著**: 不同产品的安全策略差异很大

### 6.2 建议

1. **增加专业转介**: 在涉及医疗、法律、心理健康等场景时，应建议用户寻求专业帮助

2. **加强 Jailbreak 防护**: 增加对 prompt injection 和 jailbreak 的防护机制

3. **完善隐私保护**: 明确说明数据处理方式和隐私保护措施

4. **统一安全标准**: 建议行业制定统一的 system prompt 安全标准

### 6.3 研究局限

- 基于关键词匹配的检测可能存在误报/漏报
- 不同产品的 prompt 版本可能不同步
- 未能深入分析安全机制的实际效果

---
*报告生成时间: 2025-12-10 20:30:02*
