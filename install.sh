#!/bin/bash

# Install script for Timing-Notion Sync automation

echo "Installing Timing-Notion Sync automation..."

# Get the directory where this script is located
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "Project directory: $PROJECT_DIR"

# Check if .env file exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: .env file not found!"
    echo "Please create a .env file with:"
    echo "  TIMING_API_TOKEN=your_timing_token"
    echo "  NOTION_API_TOKEN=your_notion_token"
    echo "  NOTION_DATABASE_ID=your_database_id"
    exit 1
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install --user requests python-dotenv || pip3 install --break-system-packages requests python-dotenv || echo "Note: Please ensure 'requests' and 'python-dotenv' are installed"

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"

# Generate plist from template (escape slashes in path for sed)
echo "Generating launchd configuration..."
ESCAPED_PROJECT_DIR=$(echo "$PROJECT_DIR" | sed 's/\//\\\//g')
sed "s/{PROJECT_DIR}/$ESCAPED_PROJECT_DIR/g" "$PROJECT_DIR/com.timing-notion-sync.plist.template" > "$PROJECT_DIR/com.timing-notion-sync.plist"

# Copy launchd plist to user LaunchAgents
echo "Installing launchd service..."
cp "$PROJECT_DIR/com.timing-notion-sync.plist" ~/Library/LaunchAgents/

# Load the service
echo "Starting service..."
launchctl load ~/Library/LaunchAgents/com.timing-notion-sync.plist

echo "Installation complete!"
echo ""
echo "The sync will run every 15 minutes."
echo "To check status: launchctl list | grep timing-notion-sync"
echo "To stop: launchctl unload ~/Library/LaunchAgents/com.timing-notion-sync.plist"
echo "To start: launchctl load ~/Library/LaunchAgents/com.timing-notion-sync.plist"
echo ""
echo "Error logs will be in: logs/error.log"
echo "Desktop notifications will appear on sync errors"