#!/usr/bin/env bash
# 🔬 STRICT MODE - Thorough validation of servers
# Tests with multiple retries and strict TLS verification
# Usage: ./tools/fetch-and-pick-strict.sh

set -euo pipefail

START_TIME=$(date +%s)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "🔬 STRICT MODE: Thorough server validation (~10-15 min)..."
echo "    - Multi-try ping tests"
echo "    - Strict TLS certificate validation"
echo "    - Higher concurrency for faster checks"
echo ""

TRIES=2 \
LIMIT=200 \
TOP=10 \
TIMEOUT=2.0 \
CONCURRENCY=50 \
RETRY=1 \
bash ./tools/fetch-and-pick.sh

# Show timing
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo ""
echo "🔬 Strict validation completed in ${DURATION}s"
