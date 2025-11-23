#!/bin/bash

echo "================================================"
echo "  Update Prolific Completion Code"
echo "================================================"
echo ""

# Get completion code from user
echo "Enter your Prolific Completion Code (e.g., ABCD1234):"
read -r COMPLETION_CODE

if [ -z "$COMPLETION_CODE" ]; then
    echo "❌ Error: Completion code cannot be empty!"
    exit 1
fi

echo ""
echo "Updating surveyflow/end.jsonl with code: $COMPLETION_CODE"

# Update end.jsonl
cat > surveyflow/end.jsonl << EOF
{"id":"1","text":"Thank you for completing the study","schema": "pure_display", "choices": ["<a href=\"https://app.prolific.com/submissions/complete?cc=${COMPLETION_CODE}\">Click here to return to Prolific and confirm completion</a>"]}
EOF

echo "✅ Updated!"
echo ""
echo "Next steps:"
echo "1. Run: ./restart_for_test.sh"
echo "2. Test with: http://54.193.149.43:8000/?PROLIFIC_PID=test_001"
echo "3. Check the end page shows your completion code"
echo ""

