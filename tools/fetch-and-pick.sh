#!/usr/bin/env bash
set -euo pipefail

START_TIME=$(date +%s)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "🔄 Updating configs from upstream (https://github.com/zieng2/wl)..."
git fetch upstream main
git checkout upstream/main -- vless*.txt README.md 2>/dev/null || true

echo "📋 Available config files:"
ls -lh vless*.txt

# Configuration parameters (optimized for speed)
TRIES="${TRIES:-1}"
MIN_SUCCESSES="${MIN_SUCCESSES:-1}"
TOP="${TOP:-10}"
SUBSCRIPTION="${SUBSCRIPTION:-vless_universal.txt}"
OUT_DIR="${OUT_DIR:-local-out}"
LIMIT="${LIMIT:-150}"
TIMEOUT="${TIMEOUT:-2.0}"
CONCURRENCY="${CONCURRENCY:-100}"

# Create output directory
mkdir -p "$OUT_DIR"

echo ""
echo "⚡ Running VPN picker to find fastest $TOP servers..."
echo "   Using source: $SUBSCRIPTION"

run_picker() {
  local max_cv="$1"
  local max_ping_spread="$2"
  local args=(
    "--subscription" "$SUBSCRIPTION"
    "--top" "$TOP"
    "--limit" "$LIMIT"
    "--tries" "$TRIES"
    "--min-successes" "$MIN_SUCCESSES"
    "--schemes" "${SCHEMES:-vless}"
    "--timeout" "$TIMEOUT"
    "--concurrency" "$CONCURRENCY"
    "--out-dir" "$OUT_DIR"
    "--use-icmp"
    "--max-cv" "$max_cv"
    "--max-ping-spread" "$max_ping_spread"
  )
  python3 "$ROOT_DIR/tools/vpn_picker.py" "${args[@]}" 2>&1 || true
}

run_picker "20" "2.0"

count_top() {
  if [ -f "$OUT_DIR/top.txt" ]; then
    grep -cve '^[[:space:]]*$' "$OUT_DIR/top.txt" || echo 0
  else
    echo 0
  fi
}

current_top_count=$(count_top)

# Only retry if configured for more strict testing
if [ "$current_top_count" -lt "$TOP" ] && [ "$TOP" -gt 0 ] && [ "${RETRY:-1}" = "1" ]; then
  echo "⚠️  Found only $current_top_count of $TOP servers, relaxing filters..."
  run_picker "30" "4.0"
  current_top_count=$(count_top)
fi

# Copy results to top-10.txt
if [ -f "$OUT_DIR/top.txt" ] && [ "$current_top_count" -gt 0 ]; then
  echo ""
  echo "✅ Found $current_top_count fastest servers!"
  cp "$OUT_DIR/top.txt" "$ROOT_DIR/top-10.txt"
  echo "📁 Results saved to: top-10.txt"
  echo ""
  echo "🔝 Top servers:"
  head -3 "$ROOT_DIR/top-10.txt" | sed 's/^/   /'
  echo "   ..."
else
  echo "❌ No servers found. Check your configs and network connection."
  exit 1
fi

# Commit and push
echo ""
echo "💾 Committing changes to git..."
cd "$ROOT_DIR"
git add vless*.txt top-10.txt README.md 2>/dev/null || true
if git diff --cached --quiet; then
  echo "ℹ️  No changes to commit"
else
  TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
  git commit -m "⚡ Auto-update: $(echo $current_top_count) fastest servers ($TIMESTAMP)" || true
fi

echo ""
echo "🚀 Pushing to GitHub..."
git pull --no-rebase origin main || true
git push origin main || echo "⚠️  Push failed (conflicts?), manual review needed"

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo ""
echo "✨ Done! Completed in ${DURATION}s"
echo "📊 Results: https://github.com/mGentel1309/Vpn/blob/main/top-10.txt"
