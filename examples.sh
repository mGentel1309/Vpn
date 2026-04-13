#!/usr/bin/env bash
# Usage examples for improved vpn_picker.py with stability metrics
# Run from repo root: bash examples.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "📊 VPN Picker Examples - New Stability Metrics"
echo "=============================================="
echo ""

# Example 1: Super stable servers only
echo "1️⃣  SUPER STABLE SERVERS (CV < 10%, Spread < 1.5ms)"
echo "   Command:"
echo "   python3 tools/vpn_picker.py --max-cv 10 --max-ping-spread 1.5 --tries 5 --top 5"
echo ""

# Example 2: Balanced selection
echo "2️⃣  BALANCED: Speed vs Stability (CV < 25%, 5 tries)"
echo "   Command:"
echo "   python3 tools/vpn_picker.py --max-cv 25 --tries 5 --top 10"
echo ""

# Example 3: Performance focused
echo "3️⃣  PERFORMANCE FOCUSED: Lowest ping (no stability filter)"
echo "   Command:"
echo "   python3 tools/vpn_picker.py --tries 3 --top 10"
echo ""

# Example 4: Strict filtering
echo "4️⃣  VERY STRICT: Only bullet-proof servers (CV < 15%, Spread < 2ms)"
echo "   Command:"
echo "   python3 tools/vpn_picker.py --max-cv 15 --max-ping-spread 2.0 --tries 5 --min-successes 4 --top 3"
echo ""

# Example 5: Mobile-friendly (low latency variance)
echo "5️⃣  MOBILE-FRIENDLY: Low variance pings (Spread < 1ms, min 5 tries)"
echo "   Command:"
echo "   python3 tools/vpn_picker.py --max-ping-spread 1.0 --tries 5 --min-successes 4 --top 5"
echo ""

# Example 6: Check stability of existing configs
echo "6️⃣  ANALYZE SPECIFIC CONFIG FILE (e.g., Vless-Reality)"
echo "   Command:"
echo "   python3 tools/vpn_picker.py --subscription Vless-Reality-White-Lists-Rus-Mobile.txt --max-cv 30 --top 20"
echo ""

# Example 7: Extended testing
echo "7️⃣  EXTENDED TESTING: More tries for reliable results (10 pings)"
echo "   Command:"
echo "   python3 tools/vpn_picker.py --tries 10 --min-successes 8 --top 10"
echo ""

echo "📈 METRICS EXPLANATION:"
echo "   ping_ms  = Median latency (primary metric)"
echo "   stdev    = Standard deviation of pings"
echo "   cv%      = Coefficient of variation (100 × stdev / mean)"
echo "   spread   = Range (max - min) of pings"
echo ""

echo "💡 RECOMMENDATIONS:"
echo "   • Use --max-cv 10-15 for ultra-reliable VPN"
echo "   • Use --max-cv 20-25 for balanced performance"
echo "   • Don't use --max-cv for maximum speed (consider all servers)"
echo "   • Higher --tries = more accurate stability metrics"
echo "   • Mobile users should prefer lower spread values"
echo ""

echo "📊 VIEW RESULTS:"
echo "   cat local-out/ping_top.tsv          # Detailed table"
echo "   cat local-out/report.json           # Full JSON report"
echo "   cat local-out/best.txt              # Best single server"
