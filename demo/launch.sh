#!/usr/bin/env bash
# Launch all 15 demo annotation servers.
# Run from the repository root: bash demo/launch.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/.logs"

mkdir -p "$LOG_DIR"
: > "$LOG_DIR/pids.txt"

echo "============================================="
echo "  Potato Demo Suite — Launching 15 servers"
echo "============================================="
echo ""

# Step 1: Generate pre-populated annotation data
echo "Step 1/2: Generating pre-populated annotation data..."
python3 "$SCRIPT_DIR/setup_data.py"
echo ""

# Step 2: Launch servers
echo "Step 2/2: Starting servers..."
echo ""

TASKS=(
    "01-sentiment-admin:8001"
    "02-toxicity-conditional:8002"
    "03-ner-spans:8003"
    "04-moderation-custom:8004"
    "05-image-classification:8005"
    "06-audio-emotion:8006"
    "07-video-analysis:8007"
    "08-multimodal:8008"
    "09-adjudication:8009"
    "10-full-workflow:8010"
    "11-text-classify-slider:8011"
    "12-image-bbox:8012"
    "13-dependency-tree:8013"
    "14-elan-tiered:8014"
    "15-agentic-chat:8015"
)

for entry in "${TASKS[@]}"; do
    task="${entry%%:*}"
    port="${entry##*:}"
    config="demo/$task/config.yaml"
    log="$LOG_DIR/$task.log"

    # Kill any existing process on this port
    existing_pid=$(lsof -ti:"$port" 2>/dev/null || true)
    if [ -n "$existing_pid" ]; then
        echo "  Port $port in use (PID $existing_pid), killing..."
        kill -9 $existing_pid 2>/dev/null || true
        sleep 0.5
    fi

    # Task 01: keep login visible for demo
    # Task 10: keep full phase flow (consent → training → annotation)
    # Task 09: no debug (adjudicator needs to log in)
    # All others: debug mode, skip straight to annotation
    debug_flags=""
    if [ "$task" != "01-sentiment-admin" ] && \
       [ "$task" != "10-full-workflow" ] && \
       [ "$task" != "09-adjudication" ]; then
        debug_flags="--debug --debug-phase annotation"
    fi

    echo "  Starting $task on port $port... $debug_flags"
    cd "$REPO_ROOT"
    python3 potato/flask_server.py start "$config" -p "$port" $debug_flags > "$log" 2>&1 &
    pid=$!
    echo "$pid:$port:$task" >> "$LOG_DIR/pids.txt"

    # Small delay to avoid port conflicts
    sleep 0.3
done

# Wait a moment for servers to initialize
echo ""
echo "Waiting for servers to initialize..."
sleep 3

echo ""
echo "============================================="
echo "  All servers launched!"
echo "============================================="
echo ""
printf "%-6s  %-35s  %s\n" "Port" "Task" "URL"
printf "%-6s  %-35s  %s\n" "----" "----" "---"
for entry in "${TASKS[@]}"; do
    task="${entry%%:*}"
    port="${entry##*:}"
    printf "%-6s  %-35s  %s\n" "$port" "$task" "http://localhost:$port"
done
echo ""
echo "Special URLs:"
echo "  Admin Dashboard:  http://localhost:8001/admin  (API key: demo-key)"
echo "  Adjudication:     http://localhost:8009/adjudicate  (login as: adjudicator)"
echo "  Agentic Chat:     http://localhost:8015/annotate  (chat with a simulated agent)"
echo ""
echo "Logs: $LOG_DIR/"
echo "Stop:  bash demo/stop.sh"
