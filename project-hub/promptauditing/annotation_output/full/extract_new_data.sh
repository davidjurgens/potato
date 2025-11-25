#!/bin/bash
echo "==================================================="
echo "  提取指定时间之后的新数据"
echo "==================================================="
echo ""

if [ -z "$1" ]; then
    echo "❌ 请提供时间参数！"
    echo ""
    echo "用法示例："
    echo "  ./extract_new_data.sh '2025-11-25 00:00'  # 11月25日凌晨之后的数据"
    echo "  ./extract_new_data.sh '10 minutes ago'     # 最近10分钟的数据"
    echo "  ./extract_new_data.sh '1 hour ago'         # 最近1小时的数据"
    echo "  ./extract_new_data.sh '2025-11-24'         # 11月24日之后的数据"
    exit 1
fi

TIMESTAMP="$1"
OUTPUT_FILE="new_data_$(date +%Y%m%d_%H%M%S).jsonl"

echo "⏰ 查找时间: $TIMESTAMP 之后的数据"
echo "📁 输出文件: $OUTPUT_FILE"
echo ""

# 查找指定时间之后修改的用户目录
echo "🔍 查找新用户..."
NEW_USERS=$(find . -maxdepth 1 -type d -newermt "$TIMESTAMP" ! -name "." | wc -l)
echo "✅ 找到 $NEW_USERS 个新用户"
echo ""

# 提取新数据（从用户目录中）
echo "📝 提取新数据..."
> "$OUTPUT_FILE"

COUNT=0
find . -maxdepth 1 -type d -newermt "$TIMESTAMP" ! -name "." | while read dir; do
    if [ -f "$dir/assigned_user_data.jsonl" ]; then
        cat "$dir/assigned_user_data.jsonl" >> "$OUTPUT_FILE"
        COUNT=$((COUNT + 1))
    fi
done

LINES=$(wc -l < "$OUTPUT_FILE" 2>/dev/null || echo 0)
echo "✅ 提取完成！共 $LINES 条新数据"
echo ""
echo "📊 新数据保存在: $OUTPUT_FILE"
echo ""
echo "查看新数据:"
echo "  cat $OUTPUT_FILE | jq ."
echo "  或者: head -5 $OUTPUT_FILE"
