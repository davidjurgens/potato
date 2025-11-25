# 数据质量控制策略

## 📊 当前数据质量状况

**73条收集数据的质量分布：**
- 🟢 **高质量 (≥70分)**: 29条 (39.7%)
- 🟡 **中等质量 (40-69分)**: 20条 (27.4%)
- 🔴 **低质量 (<40分)**: 24条 (32.9%)

**可用数据率**: 67.1% (高+中等)

---

## 🎯 三层质量控制策略

### 1️⃣ **预防性控制 (Prevention)** - 减少噪音产生

#### ✅ 已实施：
- [x] Intro页面增强说明（正确vs错误示例）
- [x] 输入框Placeholder提示格式
- [x] Standard关键特征黄色提示框
- [x] 200字符最小长度要求
- [x] Reference Example展示完整格式

#### 🔧 建议进一步实施：

**A. 强制性Training阶段**
```python
# 在正式任务前添加1-2个练习题
训练题1: "请为Shopping Assistant + Capability Deception写system prompt"
用户提交 → 自动检查格式 → 给出反馈
通过后才能进入正式任务
```

**B. 实时格式验证**
```javascript
// 当用户输入时实时检查
if (!prompt.startsWith("You are")) {
    显示警告: "⚠️ Your prompt should start with 'You are a [Agent Name]'"
}
```

**C. 提交前强制检查清单**
```javascript
提交时弹出：
☐ Does your prompt start with "You are a/an [Agent Name]"?
☐ Does it contain instruction verbs (tell, ask, claim, etc.)?
☐ Is it at least 200 characters long?
☐ Does it match the [Standard Name] behavior?

必须勾选所有项才能提交
```

**D. 增加奖励机制**
```
质量分数 > 80分 → 额外奖励 $0.20
激励用户提供高质量数据
```

---

### 2️⃣ **自动化过滤 (Automated Filtering)** - 快速筛选

#### ✅ 已实现工具：`filter_quality_data.py`

**评分标准：**
```python
格式得分 (60%权重):
  - 以"You are"开头: +40分
  - 包含指令动词: +30分
  - 长度充足: +20-30分
  - 无无意义内容: 不扣分
  - 有无意义内容: -50分

Standard对齐得分 (40%权重):
  - 匹配2+关键词: +100分
  - 匹配1个关键词: +50分
  - 无匹配: 0分

总分 = 格式分 * 0.6 + 对齐分 * 0.4
```

**使用方法：**
```bash
python3 filter_quality_data.py

输出：
• high_quality_data.json (≥70分) → 直接使用
• medium_quality_data.json (40-69分) → 人工审核
• low_quality_data.json (<40分) → 丢弃
```

---

### 3️⃣ **人工审核 (Manual Review)** - 最终把关

#### A. 审核流程

**第一轮：快速筛选（5-10秒/条）**
```
查看：high_quality_data.json (29条)
标准：
  ✅ 格式正确（You are...）
  ✅ 有明确的恶意指令
  ✅ 符合assigned standard
  ✅ 语义通顺

标记：Pass / Need Review / Reject
```

**第二轮：详细审核（30-60秒/条）**
```
查看：medium_quality_data.json (20条)
标准：
  - 格式是否可以接受？（You're vs You are）
  - Standard对齐是否隐含表达？
  - 是否有创造性但有效的表达？
  
标记：Accept / Reject
```

**第三轮：抽样检查（10%随机）**
```
从high_quality中随机抽取10%
确保自动过滤没有误判
```

#### B. 审核指南

**接受条件（至少满足3/4）：**
- ✅ 明确的agent身份（即使不是标准"You are"格式）
- ✅ 清晰的恶意指令
- ✅ 与assigned standard相关
- ✅ 长度充足且语义完整

**拒绝条件（任意一条）：**
- ❌ 完全偏离任务（如独角兽案例）
- ❌ 不是system prompt（是用户请求或AI输出）
- ❌ 与standard完全无关
- ❌ 过短或语义不通

---

## 📈 质量提升路线图

### Phase 1: 立即实施（本周）
- [x] 运行自动过滤脚本
- [ ] 人工审核high+medium数据（49条，约1小时）
- [ ] 生成final_clean_data.json

### Phase 2: 短期改进（下周）
- [ ] 实施实时格式验证
- [ ] 添加提交前检查清单
- [ ] 在输入框上方添加醒目的格式要求

### Phase 3: 中期优化（2-4周）
- [ ] 添加Training阶段（2个练习题）
- [ ] 实施质量奖励机制
- [ ] 收集新的100条数据测试效果

### Phase 4: 长期完善（1-2个月）
- [ ] 分析高质量用户特征
- [ ] 针对性招募高质量participants
- [ ] 建立质量预测模型

---

## 🎯 目标质量指标

**当前状态：**
- 高质量率: 39.7%
- 可用率: 67.1%

**目标（Phase 2后）：**
- 高质量率: >60%
- 可用率: >85%

**目标（Phase 3后）：**
- 高质量率: >75%
- 可用率: >90%

---

## 💾 生成的质量控制文件

### 自动生成：
```
user_data/
├── collected_with_categories.json    # 原始数据(73条)
├── high_quality_data.json           # 高质量(29条) ← 直接使用
├── high_quality_data.csv            # 高质量CSV版本
├── medium_quality_data.json         # 中等(20条) ← 需人工审核
├── low_quality_data.json            # 低质量(24条) ← 丢弃
└── final_clean_data.json            # 待生成：最终清洁数据
```

### 人工审核后生成：
```
user_data/
└── final_clean_data.json            # 审核后的最终数据
    └── 预计：35-45条高质量数据
```

---

## 📝 快速行动指南

### 立即可做的3件事：

**1. 获取高质量数据（5分钟）**
```bash
# 数据已自动过滤，直接使用
使用文件: user_data/high_quality_data.json (29条)
用于: 初步分析、模型训练、论文展示
```

**2. 人工审核中等质量数据（30分钟）**
```bash
# 打开文件逐条审核
文件: user_data/medium_quality_data.json (20条)
标记: 哪些可以保留（预计12-15条）
```

**3. 更新UI（30分钟）**
```bash
# 实施实时验证和提交检查
修改: templates/malicious_prompt_layout.html
添加: 实时格式检查 + 提交前确认
```

---

## 🔬 研究价值评估

**29条高质量数据足够用于：**
- ✅ Exploratory analysis
- ✅ Proof of concept
- ✅ Initial pattern discovery
- ✅ Pilot study publication

**35-45条审核后数据足够用于：**
- ✅ Conference paper
- ✅ Workshop presentation
- ✅ Preliminary model evaluation

**100+条高质量数据需要用于：**
- ⏳ Journal publication
- ⏳ Comprehensive benchmark
- ⏳ Production model training

**建议**: 基于当前29条高质量数据进行初步分析，并行实施Phase 2改进，再收集100条新数据。

---

## 📞 联系与讨论

如需讨论：
- 审核标准的调整
- 质量阈值的设定
- 特殊案例的处理
- 后续改进方案

请随时提出！

