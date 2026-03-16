#!/bin/bash
# Build Demo Space for HuggingFace Spaces Deployment
#
# Assembles a deployable Space directory from the Potato repository.
# The output can be pushed directly to a HuggingFace Space repo.
#
# Usage:
#   ./deployment/huggingface-spaces/build_demo_space.sh [output_dir]
#
# Default output: ./demo-space-build/

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/demo-space-build}"

echo "Building Potato Demo Space..."
echo "  Source: $REPO_ROOT"
echo "  Output: $OUTPUT_DIR"

# Clean and create output directory
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# Copy the HF Spaces README (contains frontmatter)
cp "$SCRIPT_DIR/demo-space/README.md" "$OUTPUT_DIR/README.md"

# Copy Dockerfile and entrypoint
cp "$SCRIPT_DIR/demo-space/Dockerfile" "$OUTPUT_DIR/Dockerfile"
cp "$SCRIPT_DIR/demo-space/entrypoint.sh" "$OUTPUT_DIR/entrypoint.sh"
chmod +x "$OUTPUT_DIR/entrypoint.sh"

# Copy demo config and data
cp "$SCRIPT_DIR/demo-space/config.yaml" "$OUTPUT_DIR/config.yaml"
mkdir -p "$OUTPUT_DIR/data"
cp "$SCRIPT_DIR/demo-space/data/demo-traces.json" "$OUTPUT_DIR/data/demo-traces.json"

# Copy the potato package source
echo "Copying Potato source..."
rsync -a --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='annotation_output' \
    --exclude='demo-space-build' \
    --exclude='.claude' \
    --exclude='.deciduous' \
    --exclude='internal' \
    --exclude='recordings' \
    --exclude='solo_state' \
    --exclude='paper' \
    "$REPO_ROOT/potato/" "$OUTPUT_DIR/potato/"

# Copy essential project files
cp "$REPO_ROOT/requirements.txt" "$OUTPUT_DIR/requirements.txt"
cp "$REPO_ROOT/setup.py" "$OUTPUT_DIR/setup.py"

# Copy deployment directory for the Dockerfile COPY commands
mkdir -p "$OUTPUT_DIR/deployment/huggingface-spaces/demo-space"
cp "$SCRIPT_DIR/demo-space/config.yaml" "$OUTPUT_DIR/deployment/huggingface-spaces/demo-space/config.yaml"
cp -r "$SCRIPT_DIR/demo-space/data" "$OUTPUT_DIR/deployment/huggingface-spaces/demo-space/data"
cp "$SCRIPT_DIR/demo-space/entrypoint.sh" "$OUTPUT_DIR/deployment/huggingface-spaces/demo-space/entrypoint.sh"

echo ""
echo "Demo Space built successfully at: $OUTPUT_DIR"
echo ""
echo "To deploy to HuggingFace Spaces:"
echo "  1. Create a new Space at https://huggingface.co/new-space (Docker SDK)"
echo "  2. Clone the Space repo"
echo "  3. Copy contents of $OUTPUT_DIR into the Space repo"
echo "  4. Push to HuggingFace"
echo ""
echo "Or test locally:"
echo "  cd $OUTPUT_DIR"
echo "  docker build -t potato-demo ."
echo "  docker run -p 7860:7860 potato-demo"
