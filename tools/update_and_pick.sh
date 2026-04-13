#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

# Update from upstream
git pull upstream main --strategy recursive -X ours

# Pick best config by real validation: ICMP pinging + TLS probing (stricter checks).
# Excludes Russian servers by default (for resale outside Russia).
# Outputs top-10 fastest servers to local-out/best.txt and local-out/top.txt
TRIES="${TRIES:-3}"
MIN_SUCCESSES="${MIN_SUCCESSES:-}"
TOP="${TOP:-10}"
EXCLUDE_RUSSIA="${EXCLUDE_RUSSIA:-1}"  # 1 = exclude Russian servers (default for Happ resale)
VERIFY_TLS="${VERIFY_TLS:-1}"  # 1 = require TLS verification (default for reliability)
MAX_CV="${MAX_CV:-20}"  # default automation stability threshold in %
MAX_PING_SPREAD="${MAX_PING_SPREAD:-2.0}"  # default max ping spread in ms
ALLOW_ANYCAST="${ALLOW_ANYCAST:-0}"  # 0 = avoid anycast/CDN endpoints by default

# Auto-adjust min-successes if not explicitly set
if [ -z "$MIN_SUCCESSES" ]; then
  if [ "$TRIES" -eq 1 ]; then
    MIN_SUCCESSES=1
  else
    MIN_SUCCESSES=2
  fi
fi

run_picker() {
  local max_cv="$1"
  local max_ping_spread="$2"
  local args=(
    "--subscription" "${SUBSCRIPTION:-BLACK_VLESS_RUS_mobile.txt}"
    "--top" "$TOP"
    "--limit" "${LIMIT:-250}"
    "--tries" "$TRIES"
    "--min-successes" "$MIN_SUCCESSES"
    "--schemes" "${SCHEMES:-vless}"
    "--timeout" "${TIMEOUT:-2.5}"
    "--concurrency" "${CONCURRENCY:-50}"
    "--out-dir" "${OUT_DIR:-local-out}"
    "--use-icmp"
    "--max-cv" "$max_cv"
    "--max-ping-spread" "$max_ping_spread"
  )
  [ "$EXCLUDE_RUSSIA" = "1" ] && args+=("--exclude-russia")
  [ "$VERIFY_TLS" = "1" ] && args+=("--verify-tls")
  [ "$ALLOW_ANYCAST" = "1" ] && args+=("--allow-anycast")
  python3 "$ROOT_DIR/tools/vpn_picker.py" "${args[@]}"
}

run_picker "$MAX_CV" "$MAX_PING_SPREAD"

count_top() {
  if [ -f "$ROOT_DIR/local-out/top.txt" ]; then
    grep -cve '^[[:space:]]*$' "$ROOT_DIR/local-out/top.txt" || true
  else
    echo 0
  fi
}

current_top_count=$(count_top)
if [ "$current_top_count" -lt "$TOP" ] && [ "$TOP" -gt 0 ]; then
  echo "Warning: found only $current_top_count of $TOP servers, relaxing stability filters..."
  run_picker "30" "4.0"
  current_top_count=$(count_top)
fi

if [ "$current_top_count" -lt "$TOP" ] && [ "$TOP" -gt 0 ]; then
  echo "Warning: found only $current_top_count of $TOP servers after first relaxation, relaxing again..."
  run_picker "40" "8.0"
  current_top_count=$(count_top)
fi

if [ "$current_top_count" -lt "$TOP" ] && [ "$TOP" -gt 0 ]; then
  echo "Warning: found only $current_top_count of $TOP servers after second relaxation, keeping available results."
fi

# Update subscription.txt with the top configs
cp "$ROOT_DIR/local-out/top.txt" "$ROOT_DIR/subscription.txt"

# Commit and push changes
cd "$ROOT_DIR"
git add subscription.txt
git commit -m "Update subscription.txt with top configs" || true  # skip if nothing changed
git pull --no-rebase origin main || true  # merge remote changes
git push || true  # push fails gracefully if conflicts

