#!/usr/bin/env python3
"""
Advanced VPN Server Validator & Sorter
Performs real TCP/ICMP ping tests and sorts O(n log n) by latency
Similar to Happ's validation approach
"""

import asyncio
import socket
import subprocess
import sys
import time
import platform
from collections import defaultdict
from typing import List, Tuple, Optional
import re


class ServerTest:
    def __init__(self, config: str):
        self.config = config
        # Parse host from config
        self.host = self._extract_host()
        self.label = self._extract_label()
        self.pings: List[float] = []
        self.avg_ping: Optional[float] = None
        self.success_rate = 0.0
        
    def _extract_host(self) -> Optional[str]:
        """Extract IP/domain from vless:// config"""
        try:
            # vless://...@HOST:PORT?...
            match = re.search(r'@([^:]+):', self.config)
            return match.group(1) if match else None
        except:
            return None
    
    def _extract_label(self) -> str:
        """Extract label from config"""
        try:
            match = re.search(r'#(.+)$', self.config)
            return match.group(1) if match else "Unknown"
        except:
            return "Unknown"
    
    async def tcp_ping(self, timeout: float = 2.0) -> Optional[float]:
        """TCP connect ping - reliable check"""
        if not self.host:
            return None
        
        # Extract port from config
        try:
            match = re.search(r':(\d+)\?', self.config)
            port = int(match.group(1)) if match else 443
        except:
            port = 443
        
        start = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, port),
                timeout=timeout
            )
            rtt = (time.perf_counter() - start) * 1000
            writer.close()
            try:
                await writer.wait_closed()
            except:
                pass
            return rtt
        except:
            return None
    
    def icmp_ping(self, timeout: float = 2.0) -> Optional[float]:
        """Real ICMP ping - most reliable"""
        if not self.host:
            return None
        
        try:
            system = platform.system()
            timeout_sec = int(timeout)
            
            if system == "Darwin":  # macOS
                result = subprocess.run(
                    ["ping", "-c", "1", "-t", str(timeout_sec), self.host],
                    capture_output=True,
                    text=True,
                    timeout=timeout + 1,
                )
            else:  # Linux
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", str(int(timeout * 1000)), self.host],
                    capture_output=True,
                    text=True,
                    timeout=timeout + 1,
                )
            
            if result.returncode != 0:
                return None
            
            # Parse "time=X.XXms"
            output = result.stdout + result.stderr
            match = re.search(r'time[=:]?\s*([\d.]+)\s*m?s', output, re.IGNORECASE)
            return float(match.group(1)) if match else None
        except:
            return None
    
    async def test(self, attempts: int = 3, use_icmp: bool = True) -> bool:
        """Run ping tests and collect results"""
        if not self.host:
            return False
        
        for _ in range(attempts):
            # Try ICMP first
            if use_icmp:
                ping_ms = self.icmp_ping(timeout=2.0)
                if ping_ms is not None:
                    self.pings.append(ping_ms)
                    await asyncio.sleep(0.1)
                    continue
            
            # Fallback to TCP
            ping_ms = await self.tcp_ping(timeout=2.0)
            if ping_ms is not None:
                self.pings.append(ping_ms)
            
            await asyncio.sleep(0.1)
        
        if self.pings:
            self.avg_ping = sum(self.pings) / len(self.pings)
            self.success_rate = len(self.pings) / attempts
            return True
        
        return False


def sort_servers(servers: List[ServerTest]) -> List[ServerTest]:
    """Sort O(n log n) by average ping using Python's Timsort"""
    # Filter: only servers with >70% success rate
    valid = [s for s in servers if s.success_rate >= 0.7]
    
    # Sort O(n log n) - Python's sorted() uses Timsort (merge sort hybrid)
    return sorted(valid, key=lambda s: (s.avg_ping or float('inf')))


async def validate_servers(configs: List[str], attempts: int = 2, top: int = 10) -> List[str]:
    """Validate servers and return top N sorted by ping"""
    print(f"🔬 Validating {len(configs)} servers...")
    print(f"   - {attempts} ping attempts per server")
    print(f"   - Real ICMP + TCP fallback")
    print(f"   - Filter: >70% success required")
    print()
    
    servers = [ServerTest(config) for config in configs]
    
    # Run tests in parallel
    tasks = []
    for i, server in enumerate(servers):
        tasks.append(server.test(attempts=attempts, use_icmp=True))
        if (i + 1) % 20 == 0:
            await asyncio.gather(*tasks)
            tasks = []
            print(f"   ✓ Tested {i + 1}/{len(servers)}")
    
    if tasks:
        await asyncio.gather(*tasks)
    
    print(f"   ✓ Tested {len(servers)}/{len(servers)}")
    print()
    
    # Sort O(n log n)
    print("📊 Sorting servers by latency (O(n log n))...")
    sorted_servers = sort_servers(servers)
    
    # Report
    print(f"   ✓ Valid servers: {len(sorted_servers)} / {len(servers)}")
    if sorted_servers:
        print(f"   ✓ Fastest: {sorted_servers[0].avg_ping:.1f}ms")
        print(f"   ✓ Slowest: {sorted_servers[-1].avg_ping:.1f}ms")
    print()
    
    # Return top N configs
    return [s.config for s in sorted_servers[:top]]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 advanced_sorter.py <config_file> [top_n] [attempts]")
        print("Example: python3 advanced_sorter.py vless_universal.txt 10 2")
        sys.exit(1)
    
    config_file = sys.argv[1]
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    attempts = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    
    # Read configs
    try:
        with open(config_file, 'r') as f:
            configs = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception as e:
        print(f"❌ Error reading {config_file}: {e}")
        sys.exit(1)
    
    if not configs:
        print(f"❌ No configs found in {config_file}")
        sys.exit(1)
    
    print(f"📋 Loaded {len(configs)} server configs from {config_file}")
    print()
    
    # Run validation
    top_configs = asyncio.run(validate_servers(configs, attempts=attempts, top=top_n))
    
    if not top_configs:
        print("❌ No valid servers found!")
        sys.exit(1)
    
    # Output
    print("🏆 Top servers (sorted by latency):")
    print()
    for i, config in enumerate(top_configs, 1):
        test = ServerTest(config)
        print(f"{i:2}. [{test.avg_ping:6.1f}ms] {test.label}")
        print(f"    Config: {config[:80]}...")
        print()
    
    # Write to file
    output_file = config_file.replace('.txt', '_validated.txt')
    with open(output_file, 'w') as f:
        f.write('\n'.join(top_configs))
    
    print(f"✅ Results saved to {output_file}")
    
    # Also print raw configs for easy copy-paste
    print()
    print("📋 Raw output (paste into vpn.txt):")
    print()
    for config in top_configs:
        print(config)


if __name__ == '__main__':
    main()
