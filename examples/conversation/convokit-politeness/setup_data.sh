#!/usr/bin/env bash
# Fetch the Wikipedia Politeness corpus and build this example's data file.
#
# This corpus is still shipped in ConvoKit's LEGACY format (user/root/users.json);
# Potato detects and maps that, so nothing here mentions it. ~2MB.
set -euo pipefail
cd "$(dirname "$0")"

python ../../../potato/flask_server.py convokit wikipedia-politeness-corpus \
    --unit utterance \
    --context-window 0 \
    --tree-field "" \
    --max-conversations 300 \
    --promote-meta Binary \
    -o data/politeness.jsonl

echo
echo "Now run, from the repository root:"
echo "  python potato/flask_server.py start examples/conversation/convokit-politeness/config.yaml -p 8000"
