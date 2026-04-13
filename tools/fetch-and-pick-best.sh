#!/usr/bin/env bash
# 🏆 BEST MODE - Optimal combination (recommended for production)
# Strategy: Advanced ping validation + multiple retries
# Usage: ./tools/fetch-and-pick-best.sh

set -euo pipefail

START_TIME=$(date +%s)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "🏆 BEST MODE: Production-ready server selection (~8-12 min)..."
echo "    Strategy: Real ping + advanced sorting + validation"
echo ""

# Enhanced parameters for this mode
export SUBSCRIPTION="${SUBSCRIPTION:-vless_universal.txt}"
export TOP="${TOP:-10}"
export ATTEMPTS="${ATTEMPTS:-3}"

# Run advanced validation
bash "$ROOT_DIR/tools/fetch-and-pick-advanced.sh"

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "🏆 Best mode completed in ${DURATION}s"
echo "📊 Quality: High (3-attempt ping validation)"
echo "✅ Ready for production use"
