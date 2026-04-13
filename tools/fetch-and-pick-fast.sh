#!/usr/bin/env bash
# ⚡ FAST MODE - Get top servers in ~2-3 minutes (with strict TLS validation)
# Usage: ./tools/fetch-and-pick-fast.sh

set -euo pipefail

START_TIME=$(date +%s)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "⚡ FAST MODE: Finding top 5 fastest + verified servers (~2-3 min)..."
echo ""

TRIES=1 \
LIMIT=50 \
TOP=5 \
TIMEOUT=1.5 \
CONCURRENCY=100 \
RETRY=0 \
bash ./tools/fetch-and-pick.sh

# Show timing
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo ""
echo "⚡ Fast mode completed in ${DURATION}s"
