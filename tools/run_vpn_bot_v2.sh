#!/bin/bash
# VPN Bot v2.0 Launcher with SBP payment support

set -e

cd "$(dirname "$0")/.."

echo "🤖 Starting VPN Bot v2.0..."

# Load .env
if [ -f .env ]; then
    set -a
    source .env
    set +a
else
    echo "❌ .env file not found"
    exit 1
fi

# Check Python
PYTHON=$(which python3)
if [ -z "$PYTHON" ]; then
    echo "❌ Python3 not found"
    exit 1
fi

# Check token
if [ -z "$VPN_TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ VPN_TELEGRAM_BOT_TOKEN not set in .env"
    exit 1
fi

# Kill old bot
pkill -f "vpn_telegram_bot" || true

# Wait for port release
sleep 1

# Create bot_data directory
mkdir -p tools/bot_data

# Start new bot
echo "▶️  Running: $PYTHON tools/vpn_telegram_bot_v2.py"
nohup "$PYTHON" tools/vpn_telegram_bot_v2.py > /tmp/bot_v2.log 2>&1 &
PID=$!

echo "✅ Bot started (PID: $PID)"
echo "📋 Logs: tail -f /tmp/bot_v2.log"

# Wait a bit and check
sleep 2
if ps -p $PID > /dev/null; then
    echo "🎉 Bot is running"
else
    echo "❌ Bot failed to start"
    cat /tmp/bot_v2.log
    exit 1
fi
