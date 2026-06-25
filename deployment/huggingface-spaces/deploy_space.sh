#!/bin/bash
# Thin wrapper around deploy_space.py.
#   bash deploy_space.sh <space-id> <hf-org> [--private]
#   bash deploy_space.sh --all <hf-org> [--ready-only] [--include-gated]
#
# Authenticate first (you run this): huggingface-cli login   (or export HF_TOKEN=hf_...)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python "$SCRIPT_DIR/deploy_space.py" "$@"
