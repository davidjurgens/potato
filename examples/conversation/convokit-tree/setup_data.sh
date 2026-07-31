#!/usr/bin/env bash
# Fetch Conversations Gone Awry and build this example's data file.
#
# Both display fields read from the same import: `conversation_tree` for the
# branching view and `conversation` for the flat one. ~40MB on first run.
set -euo pipefail
cd "$(dirname "$0")"

python ../../../potato/flask_server.py convokit conversations-gone-awry-corpus \
    --unit conversation \
    --max-conversations 150 \
    --promote-meta page_title,split \
    -o data/threads.jsonl

echo
echo "Now run, from the repository root:"
echo "  python potato/flask_server.py start examples/conversation/convokit-tree/config.yaml -p 8000"
