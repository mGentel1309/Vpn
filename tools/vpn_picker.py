#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import ipaddress
import json
import os
import platform
import re
import socket
import ssl
import statistics
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple
from urllib.parse import unquote, urlsplit


UNSUPPORTED_SCHEMES = {"hysteria2", "tuic", "wireguard", "wg", "http", "https"}

CDN_HOST_SUFFIXES = (
    ".workers.dev",
    ".pages.dev",
)

CDN_IP_RANGES = (
    # Fastly (often shows up as 151.101.x.x; can be very “pingy” but poor for tunnels)
    ipaddress.ip_network("151.101.0.0/16"),
)


@dataclass(frozen=True)
class Candidate:
    raw: str
    scheme: str
    host: str
    port: int
    label: str
    query: str


def _looks_like_ipv6(host: str) -> bool:
    return ":" in host and not re.search(r"^[a-zA-Z0-9.-]+$", host)


def _parse_host_port_from_netloc(netloc: str) -> Tuple[str, int]:
    # netloc may be "user:pass@host:port" or "host:port" or "[ipv6]:port"
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    netloc = netloc.strip()
    if netloc.startswith("["):
        # [ipv6]:port
        m = re.match(r"^\[(?P<host>.+)]:(?P<port>\d+)$", netloc)
        if not m:
            raise ValueError(f"bad ipv6 netloc: {netloc}")
        return m.group("host"), int(m.group("port"))
    if netloc.count(":") >= 2 and _looks_like_ipv6(netloc) and "]" not in netloc:
        # bare ipv6 without port - unsupported for our test
        raise ValueError(f"bare ipv6 without port: {netloc}")
    if ":" not in netloc:
        raise ValueError(f"missing port in netloc: {netloc}")
    host, port_s = netloc.rsplit(":", 1)
    return host, int(port_s)


def _parse_vmess(line: str) -> Candidate:
    # vmess://<base64(json)>
    payload = line[len("vmess://") :].strip()
    # Some encoders omit padding.
    missing = (-len(payload)) % 4
    if missing:
        payload += "=" * missing
    data = base64.b64decode(payload)
    obj = json.loads(data.decode("utf-8", errors="replace"))
    host = str(obj.get("add", "")).strip()
    port = int(str(obj.get("port", "0")).strip() or "0")
    if not host or port <= 0:
        raise ValueError("vmess missing host/port")
    label = str(obj.get("ps", "")).strip()
    return Candidate(raw=line, scheme="vmess", host=host, port=port, label=label, query="")


def _parse_uri_like(line: str) -> Candidate:
    # vless://...@host:port?...#label
    # trojan://...@host:port?...#label
    # ss://...@host:port?...#label  (userinfo may be base64; not needed for ping)
    u = urlsplit(line)
    scheme = (u.scheme or "").lower()
    if not scheme or not u.netloc:
        raise ValueError("not a valid URI")
    host, port = _parse_host_port_from_netloc(u.netloc)
    label = unquote(u.fragment or "")
    return Candidate(
        raw=line,
        scheme=scheme,
        host=host,
        port=port,
        label=label,
        query=u.query or "",
    )


def iter_candidates_from_text(text: str) -> Iterable[Candidate]:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        scheme = line.split(":", 1)[0].lower()
        if scheme in UNSUPPORTED_SCHEMES:
            continue
        try:
            if scheme == "vmess":
                yield _parse_vmess(line)
            else:
                yield _parse_uri_like(line)
        except Exception:
            # skip unparsable lines
            continue


def _is_anycast_or_cdn(cand: Candidate) -> bool:
    label = (cand.label or "").lower()
    host = (cand.host or "").lower()

    if "anycast" in label:
        return True

    for suf in CDN_HOST_SUFFIXES:
        if host.endswith(suf):
            return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    return any(ip in net for net in CDN_IP_RANGES)


def _is_russian_server(cand: Candidate) -> bool:
    """Check if server is located in Russia (not suitable for resale outside Russia)."""
    label = (cand.label or "").lower()
    
    # Filter by country code and city names
    russian_indicators = {
        "russia",
        "москва",  # Moscow
        "москв",
        "санкт",  # St. Petersburg
        "екатеринбург",
        "новосибирск",
        "казань",
        "пермь",
        "волгоград",
        "краснодар",
        "рф",  # Russia Federation
        "ru ",  # Country code in label
    }
    
    return any(indicator in label for indicator in russian_indicators)


def _get_query_param(cand: Candidate, key: str) -> Optional[str]:
    if not cand.query:
        return None
    for part in cand.query.split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
        else:
            k, v = part, ""
        if k == key:
            return unquote(v)
    return None


def _probe_kind(cand: Candidate) -> str:
    sec = (_get_query_param(cand, "security") or "").lower()
    typ = (_get_query_param(cand, "type") or "").lower()
    if sec == "tls" and typ in {"ws", "http", "xhttp"}:
        return "https"
    if sec == "tls":
        return "tls"
    return "tcp"


async def _tls_handshake_ok(
    host: str,
    port: int,
    timeout_s: float,
    family: int,
    *,
    server_name: Optional[str],
) -> bool:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host=host,
                port=port,
                family=family,
                ssl=ctx,
                server_hostname=server_name or host,
            ),
            timeout=timeout_s,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _https_probe_ok(
    host: str,
    port: int,
    timeout_s: float,
    family: int,
    *,
    server_name: Optional[str],
    http_host: Optional[str],
    path: str,
) -> bool:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host=host,
                port=port,
                family=family,
                ssl=ctx,
                server_hostname=server_name or host,
            ),
            timeout=timeout_s,
        )

        req_host = (http_host or server_name or host).strip() or host
        req_path = path if path.startswith("/") else f"/{path}"
        req = (
            f"HEAD {req_path} HTTP/1.1\r\n"
            f"Host: {req_host}\r\n"
            f"User-Agent: vpn-picker/1\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("utf-8")
        writer.write(req)
        await asyncio.wait_for(writer.drain(), timeout=timeout_s)
        data = await asyncio.wait_for(reader.read(256), timeout=timeout_s)

        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        return data.startswith(b"HTTP/1.")
    except Exception:
        return False


def _icmp_ping_millis(host: str, timeout_s: float = 2.0) -> Optional[float]:
    """Perform real ICMP ping and return RTT in milliseconds."""
    try:
        system = platform.system()
        timeout_ms = int(timeout_s * 1000)
        
        # Different ping syntax for macOS vs Linux/Windows
        if system == "Darwin":  # macOS
            # macOS uses -t for timeout in seconds
            result = subprocess.run(
                ["ping", "-c", "1", "-t", str(int(timeout_s)), host],
                capture_output=True,
                text=True,
                timeout=timeout_s + 1,
            )
        else:  # Linux, Windows, etc.
            try:
                # Linux uses -W for timeout in milliseconds
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", str(timeout_ms), host],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s + 1,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # Fallback for systems without -W flag
                result = subprocess.run(
                    ["ping", "-c", "1", "-w", str(timeout_ms), host],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s + 1,
                )
        
        if result.returncode != 0:
            return None
        
        # Parse output: look for "time=X.XXms" or "time=X.XX ms"
        output = result.stdout + result.stderr
        match = re.search(r"time[=:]?\s*([\d.]+)\s*m?s", output, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None
    except Exception:
        return None


async def _tcp_connect_latency_ms(
    host: str, port: int, timeout_s: float, family: int
) -> Optional[float]:
    start = time.perf_counter()
    try:
        fut = asyncio.open_connection(host=host, port=port, family=family)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout_s)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return (time.perf_counter() - start) * 1000.0
    except Exception:
        return None


async def measure_candidate(
    cand: Candidate,
    *,
    tries: int,
    timeout_s: float,
    family: int,
    semaphore: asyncio.Semaphore,
    min_successes: int,
    use_icmp: bool = True,
    verify_tls: bool = False,
) -> dict:
    async with semaphore:
        samples: list[float] = []
        probe = _probe_kind(cand)
        probe_ok = False
        ping_method = "icmp" if use_icmp else "tcp_connect"
        
        # Try ICMP ping first (real ping, not TCP)
        if use_icmp:
            icmp_samples: list[float] = []
            for _ in range(tries):
                # Run ping in executor to avoid blocking
                loop = asyncio.get_event_loop()
                ms = await loop.run_in_executor(
                    None,
                    _icmp_ping_millis,
                    cand.host,
                    timeout_s,
                )
                if ms is not None:
                    icmp_samples.append(ms)
            
            if len(icmp_samples) >= min_successes:
                samples = icmp_samples
                ping_method = "icmp"
                # For ICMP, we don't need TCP probe validation
                probe_ok = True
        
        # If ICMP failed or not enough samples, fall back to TCP
        if not samples:
            # For all servers if verify_tls is enabled, or for TLS/HTTPS configs
            should_verify_tls = verify_tls or probe in {"tls", "https"}
            
            if should_verify_tls:
                sni = _get_query_param(cand, "sni") or None
                host_hdr = _get_query_param(cand, "host") or None
                path = _get_query_param(cand, "path") or "/"
                
                # For HTTPS or when verify_tls is enabled, try HTTPS first
                if probe == "https" or verify_tls:
                    probe_ok = await _https_probe_ok(
                        cand.host,
                        cand.port,
                        timeout_s,
                        family,
                        server_name=sni,
                        http_host=host_hdr,
                        path=path or "/",
                    )
                else:
                    probe_ok = await _tls_handshake_ok(
                        cand.host,
                        cand.port,
                        timeout_s,
                        family,
                        server_name=sni,
                    )
                
                # For TLS verification, require successful probe
                if not probe_ok:
                    return {
                        "ok": False,
                        "scheme": cand.scheme,
                        "host": cand.host,
                        "port": cand.port,
                        "label": cand.label,
                        "raw": cand.raw,
                        "probe": probe,
                        "probe_ok": False,
                        "latency_ms": None,
                        "samples_ms": [],
                        "ping_ms": None,
                        "ping_min_ms": None,
                        "ping_max_ms": None,
                        "ping_avg_ms": None,
                        "ping_method": "tls_probe",
                        "ping_note": f"Сервер недоступен: TLS проверка не пройдена.",
                    }

            for _ in range(tries):
                ms = await _tcp_connect_latency_ms(cand.host, cand.port, timeout_s, family)
                if ms is not None:
                    samples.append(ms)
            
            if len(samples) < min_successes:
                return {
                    "ok": False,
                    "scheme": cand.scheme,
                    "host": cand.host,
                    "port": cand.port,
                    "label": cand.label,
                    "raw": cand.raw,
                    "probe": probe,
                    "probe_ok": probe_ok,
                    "latency_ms": None,
                    "samples_ms": [],
                    "ping_ms": None,
                    "ping_min_ms": None,
                    "ping_max_ms": None,
                    "ping_avg_ms": None,
                    "ping_method": ping_method,
                    "ping_note": "Оба метода (ICMP + TCP) не дали результата.",
                }
            ping_method = "tcp_connect"
        
        median = statistics.median(samples)
        mn = min(samples)
        mx = max(samples)
        avg = statistics.mean(samples)
        return {
            "ok": True,
            "scheme": cand.scheme,
            "host": cand.host,
            "port": cand.port,
            "label": cand.label,
            "raw": cand.raw,
            "probe": probe,
            "probe_ok": probe_ok,
            "latency_ms": median,
            "samples_ms": samples,
            "ping_ms": median,
            "ping_min_ms": mn,
            "ping_max_ms": mx,
            "ping_avg_ms": avg,
            "ping_method": ping_method,
            "ping_note": f"Метод: {ping_method} ({'реальный ICMP пинг' if ping_method == 'icmp' else 'время подключения к host:port'}).",
        }


def _pick_family(force_ipv4: bool, force_ipv6: bool) -> int:
    if force_ipv4 and force_ipv6:
        raise ValueError("choose only one: --ipv4 or --ipv6")
    if force_ipv4:
        return socket.AF_INET
    if force_ipv6:
        return socket.AF_INET6
    return socket.AF_UNSPEC


async def main_async(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Pick lowest-latency VPN config (real ICMP ping + TCP fallback)."
    )
    p.add_argument(
        "--subscription",
        default="BLACK_VLESS_RUS_mobile.txt",
        help="Path to TXT subscription file (relative to repo root).",
    )
    p.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many best configs to output to top.txt.",
    )
    p.add_argument("--limit", type=int, default=250, help="Max candidates to test.")
    p.add_argument("--tries", type=int, default=3, help="Ping tries per config.")
    p.add_argument("--timeout", type=float, default=2.5, help="Timeout per try (sec).")
    p.add_argument("--concurrency", type=int, default=50, help="Concurrent tests.")
    p.add_argument(
        "--min-successes",
        type=int,
        default=2,
        help="Minimum successful pings required to consider config reachable.",
    )
    p.add_argument(
        "--schemes",
        default="vless",
        help="Comma-separated schemes to consider (default: vless).",
    )
    p.add_argument("--ipv4", action="store_true", help="Force IPv4 only.")
    p.add_argument("--ipv6", action="store_true", help="Force IPv6 only.")
    p.add_argument(
        "--allow-anycast",
        action="store_true",
        help="Allow Anycast/CDN endpoints (can look fast but be slow in practice).",
    )
    p.add_argument(
        "--exclude-russia",
        action="store_true",
        default=False,
        help="Exclude Russian servers (useful for resale outside Russia).",
    )
    p.add_argument(
        "--verify-tls",
        action="store_true",
        default=False,
        help="Require TLS/HTTPS verification for all servers (stricter validation).",
    )
    p.add_argument(
        "--use-icmp",
        action="store_true",
        default=True,
        help="Use real ICMP ping (default: true). Set --no-icmp to use TCP only.",
    )
    p.add_argument(
        "--no-icmp",
        dest="use_icmp",
        action="store_false",
        help="Disable ICMP ping, use TCP connect only.",
    )
    p.add_argument(
        "--max-ping-spread",
        type=float,
        default=None,
        help="Filter out servers with ping spread (max-min) exceeding this value in ms. "
             "Lower values = more stable servers only.",
    )
    p.add_argument(
        "--max-cv",
        type=float,
        default=None,
        help="Filter out servers with coefficient of variation (ping variability) exceeding this %%. "
             "Lower values = stricter stability requirement.",
    )
    p.add_argument(
        "--out-dir",
        default="local-out",
        help="Directory for outputs (relative to repo root).",
    )
    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    sub_path = (repo_root / args.subscription).resolve()
    if not sub_path.exists():
        print(f"Subscription file not found: {sub_path}", file=sys.stderr)
        return 2

    text = sub_path.read_text(encoding="utf-8", errors="replace")
    candidates = list(iter_candidates_from_text(text))
    if not candidates:
        print("No candidates found in subscription.", file=sys.stderr)
        return 3

    allowed_schemes = {
        s.strip().lower()
        for s in (args.schemes or "").split(",")
        if s.strip()
    }
    if allowed_schemes:
        candidates = [c for c in candidates if c.scheme in allowed_schemes]
        if not candidates:
            print("No candidates after scheme filter.", file=sys.stderr)
            return 3

    # Prefer “real” endpoints: Anycast/CDN can connect fast but behave poorly for tunnels.
    if not args.allow_anycast:
        filtered_candidates = [c for c in candidates if not _is_anycast_or_cdn(c)]
        if filtered_candidates:
            # Use filtered candidates if available
            candidates = filtered_candidates
        # If everything was filtered out, keep original candidates from this batch
    # Filter Russian servers if requested
    if args.exclude_russia:
        russian_count = len([c for c in candidates if _is_russian_server(c)])
        candidates = [c for c in candidates if not _is_russian_server(c)]
        if not candidates and russian_count > 0:
            print(f"Warning: All {russian_count} candidates were Russian servers (filtered out).", 
                  file=sys.stderr)
            return 3
    candidates = candidates[: max(1, int(args.limit))]
    family = _pick_family(args.ipv4, args.ipv6)
    sem = asyncio.Semaphore(max(1, int(args.concurrency)))

    results = await asyncio.gather(
        *[
            measure_candidate(
                c,
                tries=max(1, int(args.tries)),
                timeout_s=max(0.2, float(args.timeout)),
                family=family,
                semaphore=sem,
                min_successes=max(1, int(args.min_successes)),
                use_icmp=args.use_icmp,
                verify_tls=args.verify_tls,
            )
            for c in candidates
        ]
    )

    ok = [r for r in results if r["ok"]]
    
    # Calculate stability metrics for each server
    for r in ok:
        samples = r.get("samples_ms", [])
        if samples and len(samples) > 1:
            # Calculate variance and coefficient of variation for stability
            mean = statistics.mean(samples)
            variance = statistics.variance(samples)
            stdev = statistics.stdev(samples)
            cv = (stdev / mean * 100) if mean > 0 else 0  # Coefficient of variation %
            spread = max(samples) - min(samples)
            success_rate = len(samples) / max(1, int(args.tries))
        else:
            variance = 0
            stdev = 0
            cv = 0
            spread = 0
            success_rate = 1.0 if samples else 0
        
        r["_stability_score"] = {
            "stdev": stdev,
            "cv": cv,  # coefficient of variation in %
            "spread": spread,
            "success_rate": success_rate,
        }
    
    def calculate_rank_score(r):
        """Calculate composite ranking score: lower is better."""
        ping = r.get("ping_ms") if r.get("ping_ms") is not None else r.get("latency_ms") or 999
        probe_ok = 0 if r.get("probe_ok") else 1
        
        stability = r.get("_stability_score", {})
        cv = stability.get("cv", 0)
        success_rate = stability.get("success_rate", 0.5)
        
        # Normalize ping to 0-100 range (assuming 0-500ms range)
        normalized_ping = min(100, ping / 5)
        
        # Normalize CV to 0-100 range (assuming 0-50% range)
        normalized_cv = min(100, cv * 2)
        
        # Success rate penalty (0-50 points for low success rate)
        success_penalty = (1 - success_rate) * 50
        
        # Composite score = importance weights
        score = (
            probe_ok * 1000 +           # Probe pass is most important (multiply by 1000)
            normalized_ping * 10 +       # Ping latency (10x weight)
            normalized_cv * 5 +          # Stability via CV (5x weight)
            success_penalty              # Success rate (0-50 points)
        )
        
        return score, probe_ok, ping, cv
    
    ok.sort(key=calculate_rank_score)
    
    # Apply stability filters if specified
    if args.max_ping_spread is not None:
        ok = [r for r in ok if r.get("_stability_score", {}).get("spread", 0) <= args.max_ping_spread]
    
    if args.max_cv is not None:
        ok = [r for r in ok if r.get("_stability_score", {}).get("cv", 0) <= args.max_cv]
    
    # Re-sort after filtering to ensure correct order
    ok.sort(key=calculate_rank_score)

    out_dir = (repo_root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "subscription": os.path.relpath(str(sub_path), str(repo_root)),
        "tested": len(results),
        "ok": len(ok),
        "timestamp_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ping": {
            "ping_ms": "Медиана из нескольких замеров (основной критерий сортировки вместе с probe_ok).",
            "ping_min_ms": "Минимум среди замеров (ICMP или TCP).",
            "ping_max_ms": "Максимум среди замеров (ICMP или TCP).",
            "ping_avg_ms": "Среднее арифметическое замеров.",
            "samples_ms": "Сырые значения каждого замера (мс).",
            "ping_method": "ICMP (реальный пинг) или TCP connect (fallback если ICMP недоступен).",
            "disclaimer_ru": "Низкий ping_ms не гарантирует рабочий VLESS/Reality/Hysteria и не отражает пропускную способность.",
        },
        "stability": {
            "cv": "Коэффициент вариации (%) = (стев.откл. / среднее) * 100. Низкое значение = стабильный сервер.",
            "spread": "Разница между максимальным и минимальным пингом в мс.",
            "stdev": "Стандартное отклонение пинга.",
            "success_rate": "Доля успешных попыток подключения (0.0 - 1.0).",
            "disclaimer_ru": "Более стабильные серверы имеют приоритет в сортировке. Используйте --max-cv или --max-ping-spread для фильтрации.",
        },
        "best": ok[0] if ok else None,
        "top": ok[: max(1, int(args.top))],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ping_lines: list[str] = [
        "# ping_ms = медиана пинга (ICMP или TCP) (см. report.json → ping)",
        "# stdev = стандартное отклонение; cv = коэффициент вариации (%); spread = max-min",
        "# колонки: ping_ms\tmin\tmax\tavg\tstdev\tcv%\tspread\tmethod\thost:port\tscheme\tprobe_ok\tlabel",
    ]
    for r in ok[: max(1, int(args.top))]:
        if r.get("ping_ms") is None:
            continue
        stab = r.get("_stability_score", {})
        ping_lines.append(
            "{pm:.2f}\t{pmn:.2f}\t{pmx:.2f}\t{pavg:.2f}\t{stdev:.2f}\t{cv:.1f}\t{spread:.2f}\t{meth}\t{hp}\t{sch}\t{po}\t{lab}".format(
                pm=float(r["ping_ms"]),
                pmn=float(r.get("ping_min_ms") or r["ping_ms"]),
                pmx=float(r.get("ping_max_ms") or r["ping_ms"]),
                pavg=float(r.get("ping_avg_ms") or r["ping_ms"]),
                stdev=float(stab.get("stdev", 0)),
                cv=float(stab.get("cv", 0)),
                spread=float(stab.get("spread", 0)),
                meth=str(r.get("ping_method") or "tcp_connect"),
                hp=f"{r['host']}:{r['port']}",
                sch=r["scheme"],
                po="1" if r.get("probe_ok") else "0",
                lab=(r.get("label") or "").replace("\t", " "),
            )
        )
    (out_dir / "ping_top.tsv").write_text("\n".join(ping_lines) + "\n", encoding="utf-8")

    if ok:
        (out_dir / "best.txt").write_text(ok[0]["raw"] + "\n", encoding="utf-8")
        (out_dir / "top.txt").write_text(
            "\n".join([x["raw"] for x in ok[: max(1, int(args.top))]]) + "\n",
            encoding="utf-8",
        )
        print(ok[0]["raw"])
        return 0

    (out_dir / "best.txt").write_text("", encoding="utf-8")
    (out_dir / "top.txt").write_text("", encoding="utf-8")
    print("No reachable configs found (TCP connect).", file=sys.stderr)
    return 4


def main() -> int:
    try:
        return asyncio.run(main_async(sys.argv[1:]))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

