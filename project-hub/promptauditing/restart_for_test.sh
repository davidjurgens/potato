#!/bin/bash

# 停止旧的服务器
echo "🛑 Stopping old server..."
pkill -9 -f "potato start" 2>/dev/null
sleep 2

# 清空任务分配
echo "🗑️  Clearing task assignments..."
cd /home/ec2-user/PromptAuditing/newpotato/potato/project-hub/promptauditing
rm -rf annotation_output/full/*
mkdir -p annotation_output/full

# 启动服务器
echo "🚀 Starting server..."
nohup potato start configs/promptauditing.yaml -p 8000 > server.log 2>&1 &

# 等待服务器启动
echo "⏳ Waiting for server to start..."
sleep 5

# 检查服务器状态
if ps aux | grep -v grep | grep "potato start" > /dev/null; then
    echo "✅ Server is running on port 8000"
    echo ""
    echo "📋 Check logs:"
    echo "   tail -f server.log"
else
    echo "❌ Server failed to start. Check server.log for errors:"
    tail -20 server.log
fi

