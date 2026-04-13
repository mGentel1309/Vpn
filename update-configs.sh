#!/bin/bash

# Script to update configs from upstream repository
# Usage: ./update-configs.sh

echo "📥 Fetching updates from upstream (https://github.com/zieng2/wl)..."
git fetch upstream main

echo "📦 Checking out latest vless configs from upstream..."
git checkout upstream/main -- vless*.txt README.md 2>/dev/null || true

echo "✅ Configs updated!"
echo "📋 Current config files:"
ls -lh vless*.txt

echo ""
echo "💾 Committing changes..."
git add vless*.txt README.md
git commit -m "Update: Fetch latest vless configs from upstream" || echo "No changes to commit"

echo ""
echo "🚀 Pushing to origin..."
git push origin main

echo "✨ Done!"
