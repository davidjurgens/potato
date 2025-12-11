# User-Centric Malicious Prompt Analysis Report

## 研究目标

分析 **Benign System Prompts** 与 **人工收集的 Malicious Prompts** 的差异，
为 user-malicious prompt detection 提供数据支持。

## 数据概览

| 类别 | 数量 | 平均长度 |
|------|------|----------|
| **Benign** (Real System Prompts) | 211 | 19,136 字符 |
| **Malicious** (人工收集) | 1268 | 362 字符 |

**关键差异**: Benign prompts 平均长度是 Malicious 的 52.9 倍

---

## 1. 特征对比分析

### 1.1 核心特征差异

| 特征 | Benign | Malicious | 差异 | 意义 |
|------|--------|-----------|------|------|
| 以 "You are" 开头 | 31.8% | 80.3% | ↑ 48.5% | 两者都高，格式相似 |
| 包含 "guarantee" | 5.2% | 2.8% | ↓ 2.4% | Malicious 更常用承诺 |
| 包含紧迫词汇 | 44.5% | 4.8% | ↓ 39.7% | Malicious 制造紧迫感 |
| 包含情绪词汇 | 2.8% | 5.0% | ↑ 2.2% | Malicious 操纵情绪 |
| 包含隐藏/省略词 | 27.0% | 4.0% | ↓ 23.0% | Malicious 选择性披露 |
| 包含 "only" | 86.7% | 14.7% | ↓ 72.1% | Malicious 限制选择 |
| 包含 "tell user" | 10.0% | 13.5% | ↑ 3.5% | Malicious 指令性更强 |


### 1.2 指令词使用差异

| 指令词 | Benign (平均/prompt) | Malicious (平均/prompt) | 分析 |
|--------|---------------------|------------------------|------|
| Must | 9.2 | 0.1 | Benign 更规范 |
| Should | 9.5 | 0.1 | Benign 更多建议 |
| Never | 6.0 | 0.1 | Benign 有更多限制 |
| Always | 5.4 | 0.1 | Malicious 更绝对化 |
| Don't/Do not | 10.1 | 0.2 | Benign 限制更多 |

---

## 2. 基于 26 标准的检测率

### 2.1 各标准检测效果

| 排名 | 标准 | Benign | Malicious | 区分度 |
|------|------|--------|-----------|--------|
| 1 | Intent Deception | 0.0% | 2.1% | +2.1% |
| 2 | Selective Disclosure | 0.0% | 1.0% | +1.0% |
| 3 | Unauthorized Use Disclosure | 0.5% | 1.4% | +0.9% |
| 4 | Vulnerability Exploitation | 0.9% | 1.7% | +0.7% |
| 5 | Elicitation | 0.0% | 0.6% | +0.6% |
| 6 | Sycophancy & Harmful Agreement | 0.9% | 1.5% | +0.6% |
| 7 | Misinformation | 0.5% | 0.5% | -0.0% |
| 8 | Boundary Violation | 0.5% | 0.5% | -0.0% |
| 9 | False Reassurance | 0.9% | 0.9% | -0.1% |
| 10 | Emotional Manipulation | 2.4% | 1.0% | -1.3% |
| 11 | Cognitive Bias Exploitation | 4.3% | 2.1% | -2.1% |
| 12 | Intent Misinterpretation | 3.8% | 0.3% | -3.5% |
| 13 | Dependency Creation | 4.7% | 0.8% | -4.0% |
| 14 | Oversimplification | 6.6% | 1.3% | -5.3% |
| 15 | Covert Assessment | 12.8% | 1.5% | -11.3% |
| 16 | Choice Manipulation | 14.2% | 1.7% | -12.5% |
| 17 | Source Deception | 16.6% | 0.5% | -16.1% |
| 18 | Framing Manipulation | 25.6% | 2.5% | -23.1% |
| 19 | Threats & Intimidation | 28.4% | 3.2% | -25.2% |
| 20 | Rejection Ignoring | 30.8% | 3.6% | -27.2% |
| 21 | Context-Based Exploitation | 30.8% | 1.3% | -29.5% |
| 22 | Capability Deception | 41.7% | 8.6% | -33.1% |
| 23 | Urgency Manipulation | 44.1% | 4.7% | -39.3% |
| 24 | Over-Collection | 46.4% | 6.0% | -40.5% |
| 25 | Consent Assumption | 46.4% | 1.6% | -44.9% |
| 26 | Psychological Coercion | 64.0% | 6.0% | -58.0% |


### 2.2 关键发现

**高区分度标准** (Malicious 明显更高):
- **Intent Deception**: Malicious 2.1% vs Benign 0.0%
- **Selective Disclosure**: Malicious 1.0% vs Benign 0.0%
- **Unauthorized Use Disclosure**: Malicious 1.4% vs Benign 0.5%
- **Vulnerability Exploitation**: Malicious 1.7% vs Benign 0.9%
- **Elicitation**: Malicious 0.6% vs Benign 0.0%


**低区分度标准** (两者相近):
- **Over-Collection**: Malicious 6.0% vs Benign 46.4%
- **Consent Assumption**: Malicious 1.6% vs Benign 46.4%
- **Psychological Coercion**: Malicious 6.0% vs Benign 64.0%


---

## 3. 区分性词汇分析

### 3.1 Malicious Prompts 特有词汇 (Top 20)

这些词在 Malicious prompts 中出现频率远高于 Benign:

| 排名 | 词汇 | Malicious 次数 | Benign 次数 | 频率比 |
|------|------|---------------|-------------|--------|
| 1 | **helps** | 297 | 69 | 33.2x |
| 2 | **customer** | 149 | 37 | 31.1x |
| 3 | **customers** | 136 | 17 | 28.6x |
| 4 | **advice** | 116 | 34 | 24.4x |
| 5 | **legal** | 90 | 36 | 18.9x |
| 6 | **chatbot** | 88 | 11 | 18.5x |
| 7 | **health** | 90 | 39 | 17.8x |
| 8 | **online** | 83 | 27 | 17.4x |
| 9 | **social** | 82 | 32 | 17.2x |
| 10 | **emotional** | 73 | 28 | 15.3x |
| 11 | **tell** | 287 | 145 | 15.3x |
| 12 | **community** | 72 | 2 | 15.1x |
| 13 | **medical** | 69 | 22 | 14.5x |
| 14 | **mental** | 67 | 17 | 14.1x |
| 15 | **government** | 67 | 7 | 14.1x |
| 16 | **gaming** | 66 | 0 | 13.9x |
| 17 | **people** | 165 | 95 | 13.4x |
| 18 | **recommendations** | 62 | 30 | 13.0x |
| 19 | **life** | 62 | 15 | 13.0x |
| 20 | **personal** | 128 | 76 | 13.0x |


### 3.2 Benign Prompts 特有词汇 (Top 20)

这些词在 Benign prompts 中出现频率远高于 Malicious:

| 排名 | 词汇 | Benign 次数 | Malicious 次数 | 频率比 |
|------|------|-------------|---------------|--------|
| 1 | **string** | 2302 | 1 | 62.7x |
| 2 | **files** | 2274 | 5 | 59.0x |
| 3 | **tool** | 3983 | 10 | 51.6x |
| 4 | **claude** | 1639 | 0 | 44.6x |
| 5 | **tools** | 1533 | 4 | 41.8x |
| 6 | **command** | 1378 | 2 | 37.5x |
| 7 | **file** | 3686 | 13 | 36.8x |
| 8 | **query** | 1153 | 3 | 31.4x |
| 9 | **path** | 1651 | 7 | 30.6x |
| 10 | **parameters** | 928 | 0 | 25.3x |
| 11 | **description** | 2328 | 12 | 25.1x |
| 12 | **type** | 3093 | 16 | 25.1x |
| 13 | **directory** | 819 | 0 | 22.3x |
| 14 | **line** | 731 | 3 | 19.9x |
| 15 | **existing** | 760 | 5 | 19.7x |
| 16 | **image** | 723 | 1 | 19.7x |
| 17 | **output** | 731 | 5 | 19.0x |
| 18 | **edit** | 676 | 3 | 18.4x |
| 19 | **react** | 670 | 1 | 18.2x |
| 20 | **object** | 654 | 2 | 17.8x |


---

## 4. 研究启示

### 4.1 Malicious Prompts 的特征

基于分析，malicious-to-user prompts 有以下特征：

1. **长度较短**: 平均 ~360 字符 vs Benign ~19K
2. **绝对化表达**: 更多使用 "always", 较少使用 "should"
3. **缺乏限制**: 较少使用 "never", "do not" 等限制词
4. **特定词汇**: 包含承诺、紧迫、情绪操控相关词汇
5. **隐藏意图**: 更多 "hide", "omit", "don't mention" 类指令

### 4.2 检测建议

1. **长度特征**: 异常短的 system prompt 可能更可疑
2. **指令平衡**: 缺乏限制性指令 (never, do not) 是红旗
3. **关键词检测**: 关注 guarantee, urgent, only, hide 等词
4. **结构检测**: 缺乏安全条款、缺乏例外说明是可疑信号

### 4.3 分类器训练建议

已生成 `classification_dataset.json`:
- 1,479 个样本 (211 benign + 1,268 malicious)
- 可用于训练二分类器
- 建议特征: 长度、关键词频率、指令词比例

---

## 5. 输出文件

| 文件 | 内容 |
|------|------|
| `feature_comparison.json` | 特征对比数据 |
| `standard_detection_rates.json` | 26 标准检测率 |
| `distinctive_words.json` | 区分性词汇 |
| `classification_dataset.json` | 分类训练数据集 |

---

*报告生成时间: 2025-12-11 03:36:30*
