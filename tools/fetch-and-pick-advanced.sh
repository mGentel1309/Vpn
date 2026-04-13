#!/usr/bin/env bash
# ✨ ADVANCED MODE - Real ping validation with O(n log n) sorting (like Happ)
# Usage: ./tools/fetch-and-pick-advanced.sh

set -euo pipefail

START_TIME=$(date +%s)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "✨ ADVANCED MODE: Real ICMP ping + proper sorting (~5-8 min)..."
echo "    - Real ICMP ping tests (3 attempts)"
echo "    - TCP fallback validation"
echo "    - O(n log n) sorting by latency"
echo "    - Happ-like validation approach"
echo ""

# Fetch latest configs
echo "🔄 Updating configs from upstream..."
git fetch upstream main 2>/dev/null || true
git checkout upstream/main -- vless*.txt 2>/dev/null || true

# Create output directory
mkdir -p local-out

echo ""
echo "📋 Using source: ${SUBSCRIPTION:-vless_universal.txt}"

# Use advanced sorter
SUBSCRIPTION="${SUBSCRIPTION:-vless_universal.txt}"
TOP="${TOP:-10}"
ATTEMPTS="${ATTEMPTS:-3}"

echo ""
echo "⚡ Running advanced server validation..."
python3 "$ROOT_DIR/tools/advanced_sorter.py" "$SUBSCRIPTION" "$TOP" "$ATTEMPTS" 2>&1 | tee local-out/validation.log

# Save results
if [ -f "${SUBSCRIPTION%.*}_validated.txt" ]; then
  cp "${SUBSCRIPTION%.*}_validated.txt" "$ROOT_DIR/vpn.txt"
  cp "$ROOT_DIR/vpn.txt" "$ROOT_DIR/top-10.txt"
  echo ""
  echo "✅ Results saved to vpn.txt"
else
  echo "❌ Validation failed"
  exit 1
fi

# Git commit
echo ""
echo "💾 Committing changes..."
cd "$ROOT_DIR"
git add vpn.txt top-10.txt vless*.txt 2>/dev/null || true
if ! git diff --cached --quiet; then
  TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
  git commit -m "✨ Advanced: Real ping validation ($TIMESTAMP)" || true
  git pull --no-rebase origin main 2>/dev/null || true
  git push origin main || echo "⚠️  Push may have issues"
fi

# Timing
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo ""
echo "✨ Advanced validation completed in ${DURATION}s"
echo ""
echo "🎯 Results in vpn.txt:"
head -3 "$ROOT_DIR/vpn.txt"
echo "..."
