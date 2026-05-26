#!/bin/bash
# echo-ms-explorer — double-click launcher for macOS
#
# Opens the app in a native window. Terminal can be closed while the app
# keeps running. Safe to re-run anytime: any previous server is stopped first.
#
# The virtual environment is stored in ~/Library/Caches/echo-ms-explorer/venv
# (NOT in the project folder) to avoid corruption from iCloud/Dropbox sync.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# venv lives outside any synced folder (per-user, per-machine)
VENV_DIR="$HOME/Library/Caches/echo-ms-explorer/venv"
export UV_PROJECT_ENVIRONMENT="$VENV_DIR"

# Locate uv across common install locations
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
    echo ""
    echo "──────────────────────────────────────────────────────"
    echo "  echo-ms-explorer: first-time setup needed"
    echo "──────────────────────────────────────────────────────"
    echo ""
    echo "  'uv' is not installed (Python package manager)."
    echo ""
    echo "  Open Terminal and run:"
    echo ""
    echo "      curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
    echo "  Then close this window and double-click the launcher again."
    echo ""
    read -p "  Press Enter to close…"
    exit 1
fi

# ── 1. Clean up stale state from previous runs ──────────────────────────
rm -f "$SCRIPT_DIR/.server-port"
rm -f "$SCRIPT_DIR/.server.log"

# ── 2. Kill any old server still bound to our port range ────────────────
echo "Cleaning up any previous instance…"
for p in 8765 8766 8767 8768 8769 8770; do
    PIDS=$(lsof -ti :"$p" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "  stopping process(es) on port $p: $PIDS"
        kill $PIDS 2>/dev/null || true
    fi
done
sleep 1
for p in 8765 8766 8767 8768 8769 8770; do
    STILL=$(lsof -ti :"$p" 2>/dev/null || true)
    if [ -n "$STILL" ]; then
        kill -9 $STILL 2>/dev/null || true
    fi
done
sleep 1

# ── 3. Sync dependencies (fast no-op after first install) ───────────────
mkdir -p "$(dirname "$VENV_DIR")"
if [ ! -d "$VENV_DIR" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "First-time setup — installing dependencies (this may take 1-2 minutes)…"
    uv sync --python 3.12
    SYNC_RC=$?
else
    echo "Checking dependencies…"
    uv sync --quiet 2>&1 | tail -5
    SYNC_RC=${PIPESTATUS[0]}
fi

if [ "$SYNC_RC" -ne 0 ]; then
    echo ""
    echo "──────────────────────────────────────────────────────"
    echo "  Dependency setup failed."
    echo "──────────────────────────────────────────────────────"
    read -p "  Press Enter to close…"
    exit 1
fi

# ── 4. Launch the app detached from this Terminal ───────────────────────
# Using nohup + disown so the app survives even if Terminal is closed.
# The native window is created by pywebview inside launch.py.
echo "Starting echo-ms-explorer…"
LOG="$SCRIPT_DIR/.server.log"
nohup uv run python launch.py > "$LOG" 2>&1 &
APP_PID=$!
disown "$APP_PID" 2>/dev/null || true

# ── 5. Wait until the server is responding (up to 45 seconds) ───────────
PORT=""
READY=0
for i in $(seq 1 90); do
    if ! kill -0 "$APP_PID" 2>/dev/null; then
        echo ""
        echo "──────────────────────────────────────────────────────"
        echo "  App exited unexpectedly. Log output:"
        echo "──────────────────────────────────────────────────────"
        cat "$LOG" 2>/dev/null
        echo ""
        read -p "  Press Enter to close…"
        exit 1
    fi
    if [ -f "$SCRIPT_DIR/.server-port" ]; then
        PORT=$(cat "$SCRIPT_DIR/.server-port" 2>/dev/null)
        if [ -n "$PORT" ] && curl -s -o /dev/null -m 1 "http://127.0.0.1:$PORT" 2>/dev/null; then
            READY=1
            break
        fi
    fi
    sleep 0.5
done

if [ $READY -ne 1 ]; then
    echo ""
    echo "──────────────────────────────────────────────────────"
    echo "  App did not become ready in time. Log:"
    echo "──────────────────────────────────────────────────────"
    cat "$LOG" 2>/dev/null
    echo ""
    kill "$APP_PID" 2>/dev/null || true
    read -p "  Press Enter to close…"
    exit 1
fi

# ── 6. Success — the native window has opened ──────────────────────────
echo ""
echo "──────────────────────────────────────────────────────"
echo "  echo-ms-explorer is running in a native window."
echo "──────────────────────────────────────────────────────"
echo ""
echo "  This Terminal window is safe to close."
echo "  Close the app window itself to stop the app."
echo "  To restart later: double-click this launcher again."
echo ""

sleep 2
exit 0
