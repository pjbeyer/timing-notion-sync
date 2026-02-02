#!/bin/bash
# Refresh API tokens in macOS Keychain from 1Password
# Run this when tokens are rotated or after initial setup
#
# Configure your 1Password references in .env.op:
#   TIMING_API_TOKEN="op://Vault/Item/field"
#   NOTION_API_TOKEN="op://Vault/Item/field"
#   NOTION_DATABASE_ID="your-database-id"

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_FILE="$SCRIPT_DIR/.env.op"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: $CONFIG_FILE not found"
    echo ""
    echo "Create .env.op with your 1Password references:"
    echo '  TIMING_API_TOKEN="op://Vault/ItemName/credential"'
    echo '  NOTION_API_TOKEN="op://Vault/ItemName/credential"'
    exit 1
fi

source "$CONFIG_FILE"

if [ -z "$TIMING_API_TOKEN" ] || [ -z "$NOTION_API_TOKEN" ] || [ -z "$NOTION_DATABASE_ID" ]; then
    echo "ERROR: TIMING_API_TOKEN, NOTION_API_TOKEN, and NOTION_DATABASE_ID must be set in $CONFIG_FILE"
    exit 1
fi

echo "Fetching secrets from 1Password..."

TIMING_TOKEN=$(op read "$TIMING_API_TOKEN")
NOTION_TOKEN=$(op read "$NOTION_API_TOKEN")

echo "Storing secrets in macOS Keychain..."

security add-generic-password -a "$USER" -s "timing-notion-sync-timing-token" -w "$TIMING_TOKEN" -U 2>/dev/null || \
security add-generic-password -a "$USER" -s "timing-notion-sync-timing-token" -w "$TIMING_TOKEN"

security add-generic-password -a "$USER" -s "timing-notion-sync-notion-token" -w "$NOTION_TOKEN" -U 2>/dev/null || \
security add-generic-password -a "$USER" -s "timing-notion-sync-notion-token" -w "$NOTION_TOKEN"

security add-generic-password -a "$USER" -s "timing-notion-sync-notion-db" -w "$NOTION_DATABASE_ID" -U 2>/dev/null || \
security add-generic-password -a "$USER" -s "timing-notion-sync-notion-db" -w "$NOTION_DATABASE_ID"

echo "Done! Secrets refreshed in Keychain."
