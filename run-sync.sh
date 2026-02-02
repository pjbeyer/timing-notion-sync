#!/bin/bash
# Wrapper script for timing-notion-sync
# Reads API tokens from macOS Keychain, config from .env

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONPATH="$HOME/.local/lib/python/site-packages:${PYTHONPATH:-}"

cd "$SCRIPT_DIR"

# Source .env for non-secret config (DB ID, sync options)
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Override API tokens from Keychain if available (secrets only)
TIMING_TOKEN=$(security find-generic-password -a "$USER" -s "timing-notion-sync-timing-token" -w 2>/dev/null)
NOTION_TOKEN=$(security find-generic-password -a "$USER" -s "timing-notion-sync-notion-token" -w 2>/dev/null)

if [ -n "$TIMING_TOKEN" ]; then
    export TIMING_API_TOKEN="$TIMING_TOKEN"
fi

if [ -n "$NOTION_TOKEN" ]; then
    export NOTION_API_TOKEN="$NOTION_TOKEN"
fi

# Validate required config
if [ -z "$TIMING_API_TOKEN" ] || [ -z "$NOTION_API_TOKEN" ] || [ -z "$NOTION_DATABASE_ID" ]; then
    echo "ERROR: Missing required config."
    echo "  TIMING_API_TOKEN: ${TIMING_API_TOKEN:+set}${TIMING_API_TOKEN:-NOT SET}"
    echo "  NOTION_API_TOKEN: ${NOTION_API_TOKEN:+set}${NOTION_API_TOKEN:-NOT SET}"
    echo "  NOTION_DATABASE_ID: ${NOTION_DATABASE_ID:+set}${NOTION_DATABASE_ID:-NOT SET}"
    echo ""
    echo "Add API tokens to Keychain or .env, and NOTION_DATABASE_ID to .env"
    exit 1
fi

exec python3 "$SCRIPT_DIR/timing-notion-sync.py"
