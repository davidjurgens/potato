#!/usr/bin/env bash
# Stop all demo annotation servers.
# Run from the repository root: bash demo/stop.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/.logs"
PID_FILE="$LOG_DIR/pids.txt"

echo "============================================="
echo "  Potato Demo Suite — Stopping servers"
echo "============================================="
echo ""

stopped=0

# Method 1: Kill PIDs from file
if [ -f "$PID_FILE" ]; then
    while IFS=: read -r pid port task; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Stopping $task (port $port, PID $pid)..."
            kill "$pid" 2>/dev/null || true
            stopped=$((stopped + 1))
        fi
    done < "$PID_FILE"
fi

# Method 2: Fallback — kill by port range
for port in $(seq 8001 8015); do
    existing_pid=$(lsof -ti:"$port" 2>/dev/null || true)
    if [ -n "$existing_pid" ]; then
        echo "  Killing process on port $port (PID $existing_pid)..."
        kill -9 $existing_pid 2>/dev/null || true
        stopped=$((stopped + 1))
    fi
done

# Clean up PID file
if [ -f "$PID_FILE" ]; then
    rm "$PID_FILE"
fi

echo ""
if [ $stopped -gt 0 ]; then
    echo "Stopped $stopped server(s)."
else
    echo "No running demo servers found."
fi
