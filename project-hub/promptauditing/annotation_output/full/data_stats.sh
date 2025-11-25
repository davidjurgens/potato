#!/bin/bash
echo "==================================================="
echo "  📊 数据统计"
echo "==================================================="
echo ""

TOTAL_USERS=$(find . -maxdepth 1 -type d ! -name "." | wc -l)
TOTAL_LINES=$(wc -l < annotated_instances.jsonl 2>/dev/null || echo 0)

echo "📈 总体统计:"
echo "  • 总用户数: $TOTAL_USERS"
echo "  • 总提交数: $TOTAL_LINES"
echo ""

echo "📅 今天的新数据:"
TODAY=$(date +%Y-%m-%d)
TODAY_USERS=$(find . -maxdepth 1 -type d -newermt "$TODAY" ! -name "." | wc -l)
echo "  • 今天新用户: $TODAY_USERS"
echo ""

echo "⏰ 最近1小时的新数据:"
HOUR_AGO=$(date -d '1 hour ago' '+%Y-%m-%d %H:%M')
HOUR_USERS=$(find . -maxdepth 1 -type d -newermt "$HOUR_AGO" ! -name "." | wc -l)
echo "  • 最近1小时新用户: $HOUR_USERS"
echo ""

echo "📋 最新的5个提交:"
echo "---------------------------------------------------"
ls -lt | grep "^d" | head -5 | while read line; do
    DIR=$(echo $line | awk '{print $NF}')
    TIME=$(echo $line | awk '{print $6" "$7" "$8}')
    PROLIFIC_PID=$(echo $DIR | cut -d'&' -f1)
    echo "  ⏰ $TIME - $PROLIFIC_PID"
done
echo ""
echo "==================================================="
