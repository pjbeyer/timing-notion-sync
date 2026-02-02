#!/bin/bash
# Wrapper script for timing-notion-sync
# Reads secrets from macOS Keychain (no op CLI at runtime = no permission dialogs)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONPATH="$HOME/.local/lib/python/site-packages:${PYTHONPATH:-}"

cd "$SCRIPT_DIR"

# Try macOS Keychain first (secrets stored via: security add-generic-password)
TIMING_TOKEN=$(security find-generic-password -a "$USER" -s "timing-notion-sync-timing-token" -w 2>/dev/null)
NOTION_TOKEN=$(security find-generic-password -a "$USER" -s "timing-notion-sync-notion-token" -w 2>/dev/null)

NOTION_DB_ID=$(security find-generic-password -a "$USER" -s "timing-notion-sync-notion-db" -w 2>/dev/null)

if [ -n "$TIMING_TOKEN" ] && [ -n "$NOTION_TOKEN" ] && [ -n "$NOTION_DB_ID" ]; then
    export TIMING_API_TOKEN="$TIMING_TOKEN"
    export NOTION_API_TOKEN="$NOTION_TOKEN"
    export NOTION_DATABASE_ID="$NOTION_DB_ID"
    exec python3 "$SCRIPT_DIR/timing-notion-sync.py"
elif [ -f "$SCRIPT_DIR/.env" ]; then
    exec python3 "$SCRIPT_DIR/timing-notion-sync.py"
else
    echo "ERROR: No credentials found. Add secrets to Keychain or create .env file."
    exit 1
fi
