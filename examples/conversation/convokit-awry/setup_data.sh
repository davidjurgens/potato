#!/usr/bin/env bash
# Fetch the Conversations Gone Awry corpus and build this example's data file.
#
# The corpus is downloaded to ConvoKit's own cache (~/.convokit/saved-corpora by
# default), so if you already have ConvoKit installed nothing is fetched twice.
# ~40MB on first run; instant afterwards.
#
# Run from the repository root:  ./examples/conversation/convokit-awry/setup_data.sh
set -euo pipefail
cd "$(dirname "$0")"

python ../../../potato/flask_server.py convokit conversations-gone-awry-corpus \
    --unit conversation \
    --max-conversations 200 \
    --promote-meta split,page_title \
    -o data/awry.jsonl

echo
echo "Now run, from the repository root:"
echo "  python potato/flask_server.py start examples/conversation/convokit-awry/config.yaml -p 8000"
