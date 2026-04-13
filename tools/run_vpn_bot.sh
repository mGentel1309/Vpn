#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Load .env if exists
if [ -f "$ROOT_DIR/.env" ]; then
  set -o allexport
  source "$ROOT_DIR/.env"
  set +o allexport
else
  echo "❌ .env file not found. Create it from .env.example:"
  echo "   cp .env.example .env"
  echo "   nano .env"
  exit 1
fi

if [ -z "${VPN_TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "❌ VPN_TELEGRAM_BOT_TOKEN not set in .env"
  exit 1
fi

# Use system python3, not homebrew-specific
exec python3 "$ROOT_DIR/tools/vpn_telegram_bot.py"
