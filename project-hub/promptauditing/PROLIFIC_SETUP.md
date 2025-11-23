# Prolific Setup Guide

## Step 1: 在Prolific上创建Study

1. 登录 https://app.prolific.com
2. 创建新Study
3. 设置参数：
   - **Study Name**: Prompt Auditing Task
   - **Study Duration**: 2 minutes（给用户足够时间）
   - **Reward**: £0.30-£0.50（根据你的预算）
   - **Total Available Places**: 你需要的用户数（比如100）
   - **Study URL**: `http://54.193.149.43:8000/?PROLIFIC_PID={{%PROLIFIC_PID%}}`
   - **Completion Code**: Prolific会自动生成（比如：`ABCD1234`）

## Step 2: 修改配置文件

### 2.1 更新 `surveyflow/end.jsonl`

把completion code改成Prolific给你的：

```jsonl
{"id":"1","text":"Thank you for completing the study","schema": "pure_display", "choices": ["<a href=\"https://app.prolific.com/submissions/complete?cc=YOUR_COMPLETION_CODE\">Click here to return to Prolific and confirm completion</a>"]}
```

把 `YOUR_COMPLETION_CODE` 替换成Prolific给你的code。

### 2.2 调整 `configs/promptauditing.yaml`

```yaml
"automatic_assignment": {
  "on": True,
  "output_filename": 'task_assignment.json',
  "sampling_strategy": 'random',
  "labels_per_instance": 3,        # 每个实例收集3个回答
  "instance_per_annotator": 1,     # 每个用户只做1个任务
  "test_question_per_annotator": 0,
  "users": [],
}
```

**重要参数说明：**
- `labels_per_instance`: 每个数据实例你想要多少个人回答（3-5个比较好）
- `instance_per_annotator`: 每个用户做几个任务（1个任务=1分钟，根据你付费调整）

### 2.3 （可选）创建 prolific_config.yaml

如果想用Prolific API自动管理：

```yaml
{
    "token": "YOUR_PROLIFIC_API_TOKEN",
    "study_id": "YOUR_STUDY_ID",
    "max_concurrent_sessions": 10,
    "workload_checker_period": 60
}
```

**注意：不创建这个文件也可以，只是不会自动检查Prolific状态。**

## Step 3: 测试流程

在Prolific发布前，用Preview链接测试：

```
http://54.193.149.43:8000/?PROLIFIC_PID=test_preview_001
```

**检查：**
- [ ] 能看到intro页面
- [ ] 能看到consent页面
- [ ] 能看到任务（scenario/standard/example正确显示）
- [ ] 能提交回答
- [ ] 能看到end页面和completion code链接
- [ ] 点击链接能正确跳转到Prolific

## Step 4: 在Prolific上发布

1. 确保服务器在运行：
   ```bash
   cd /home/ec2-user/PromptAuditing/newpotato/potato/project-hub/promptauditing
   ./restart_for_test.sh
   ```

2. 在Prolific点击 "Publish"

3. 监控：
   ```bash
   cd /home/ec2-user/PromptAuditing/newpotato/potato/project-hub/promptauditing
   tail -f server.log
   ```

## Step 5: 收集数据

数据保存在：
```
annotation_output/full/
```

## 常见问题

### Q: 用户说看不到任务？
A: 检查 `labels_per_instance` 是否设置够大。如果是100个用户，设置成100以上。

### Q: 用户能重复做任务吗？
A: 不能。每个PROLIFIC_PID只能做一次。Potato会自动记录。

### Q: 如何计算需要多少Places？
A: 公式：`总数据量 × labels_per_instance = 需要的Places`
   例如：1000条数据 × 3个回答 = 3000个Places

### Q: 服务器停了怎么办？
A: 用户会看到连接错误。需要：
   1. 重启服务器
   2. 在Prolific暂停study
   3. 等服务器稳定后再恢复

## 价格建议

- **1分钟任务**: £0.20-£0.30
- **2分钟任务**: £0.40-£0.50
- Prolific最低工资标准：£6/hour

## 数据导出

完成后导出数据：
```bash
cd annotation_output/full/
ls *.jsonl  # 查看所有提交的数据
```

