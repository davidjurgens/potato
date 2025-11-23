#!/bin/bash

# 清空任务分配（不重启服务器）
echo "🗑️  Clearing task assignments..."
cd /home/ec2-user/PromptAuditing/newpotato/potato/project-hub/promptauditing
rm -rf annotation_output/full/*
mkdir -p annotation_output/full

echo "✅ Tasks cleared! You can test again with:"
echo "   http://54.193.149.43:8000/?PROLIFIC_PID=test_user_001"

