#!/usr/bin/env python3
import json
import math
import os
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROUNDS = int(os.getenv("ROUNDS", "2"))
IPERF_SECONDS = int(os.getenv("IPERF_SECONDS", "10"))
IPERF_STREAMS = int(os.getenv("IPERF_STREAMS", "4"))
USER_MBPS = float(os.getenv("USER_MBPS", "100"))
SAFETY_FACTOR = float(os.getenv("SAFETY_FACTOR", "0.70"))
TIMEOUT = int(os.getenv("TIMEOUT", "240"))
RESULT_FILE = Path(os.getenv("RESULT_FILE", "/results/vps-benchmark-results.json"))

HTTP_SIZES = [("10MB", 10_000_000), ("100MB", 100_000_000), ("1GB", 1_000_000_000)]
HTTP_URL = "https://speed.cloudflare.com/__down?bytes={}"

# Override IPERF_SERVERS_JSON with a JSON array if you want other servers.
DEFAULT_IPERF_SERVERS = [
    {"host": "ping.online.net", "port": 5200, "region": "FR-Scaleway"},
    {"host": "ping-90ms.online.net", "port": 5200, "region": "FR-Scaleway"},
    {"host": "iperf3.moji.fr", "port": 5200, "region": "FR-Moji"},
    {"host": "speedtest.milkywan.fr", "port": 9200, "region": "FR-MilkyWan"},
    {"host": "paris.bbr.iperf.bytel.fr", "port": 9200, "region": "FR-Paris-BBR"},
    {"host": "paris.cubic.iperf.bytel.fr", "port": 9200, "region": "FR-Paris-Cubic"},
    {"host": "mrs.bbr.iperf.bytel.fr", "port": 9200, "region": "FR-Mrs-BBR"},
    {"host": "lyo.bbr.iperf.bytel.fr", "port": 9200, "region": "FR-Lyon-BBR"},
    {"host": "tls.bbr.iperf.bytel.fr", "port": 9200, "region": "FR-Tls-BBR"},
    {"host": "ren.bbr.iperf.bytel.fr", "port": 9200, "region": "FR-Ren-BBR"},
    {"host": "speedtest1.serverius.net", "port": 5002, "region": "NL-Serverius"},
    {"host": "speedtest2.serverius.net", "port": 5002, "region": "NL-Serverius"},
    {"host": "speedtest3.serverius.net", "port": 5002, "region": "NL-Serverius"},
]
IPERF_SERVERS_JSON = os.getenv("IPERF_SERVERS_JSON", "").strip()
try:
    IPERF_SERVERS = json.loads(IPERF_SERVERS_JSON) if IPERF_SERVERS_JSON else DEFAULT_IPERF_SERVERS
except json.JSONDecodeError as exc:
    raise SystemExit(f"Invalid IPERF_SERVERS_JSON: {exc}")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(command, timeout=TIMEOUT):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=True)


def mbps(bits_per_second):
    return bits_per_second / 1_000_000


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * p / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] if lo == hi else values[lo] * (hi - pos) + values[hi] * (pos - lo)


def record_speedtest(tool, data, parser):
    if parser == "ookla":
        download = mbps(data["download"]["bandwidth"] * 8)
        upload = mbps(data["upload"]["bandwidth"] * 8)
        ping = data.get("ping", {}).get("latency")
        server = data.get("server", {}).get("name")
    else:
        download = mbps(data["download"])
        upload = mbps(data["upload"])
        ping = data.get("ping")
        server = data.get("server", {}).get("name")
    return {"type": "speedtest", "tool": tool, "download_mbps": download,
            "upload_mbps": upload, "ping_ms": ping, "server": server, "timestamp": now()}


def speedtest_ookla():
    if not shutil.which("speedtest"):
        print("[SKIP] Ookla CLI not installed")
        return []
    results = []
    for i in range(ROUNDS):
        print(f"[OOKLA] {i + 1}/{ROUNDS}", flush=True)
        try:
            data = json.loads(run(["speedtest", "--accept-license", "--accept-gdpr", "--format=json"]).stdout)
            item = record_speedtest("Ookla", data, "ookla")
            results.append(item)
            print(f"  DL {item['download_mbps']:.1f} | UL {item['upload_mbps']:.1f} Mbit/s", flush=True)
        except Exception as exc:
            print(f"  [ERROR] {exc}", flush=True)
        time.sleep(2)
    return results


def speedtest_python():
    if not shutil.which("speedtest-cli"):
        print("[SKIP] speedtest-cli not installed")
        return []
    results = []
    for i in range(ROUNDS):
        print(f"[SPEEDTEST-CLI] {i + 1}/{ROUNDS}", flush=True)
        try:
            data = json.loads(run(["speedtest-cli", "--json"]).stdout)
            item = record_speedtest("speedtest-cli", data, "python")
            results.append(item)
            print(f"  DL {item['download_mbps']:.1f} | UL {item['upload_mbps']:.1f} Mbit/s", flush=True)
        except Exception as exc:
            print(f"  [ERROR] {exc}", flush=True)
        time.sleep(2)
    return results


def curl_download(label, size_bytes):
    print(f"[CURL] {label}: {size_bytes:,} bytes", flush=True)
    try:
        output = run([
            "curl", "-L", "-f", "-sS", "--connect-timeout", "15",
            "--max-time", str(TIMEOUT), "-o", "/dev/null",
            "-w", "%{http_code} %{size_download} %{speed_download} %{time_total}",
            HTTP_URL.format(size_bytes),
        ], timeout=TIMEOUT + 10).stdout.strip()
        code, downloaded, bytes_per_second, seconds = output.split()
        downloaded, seconds = float(downloaded), float(seconds)
        speed = float(bytes_per_second) * 8 / 1_000_000
        if not 200 <= int(code) < 300 or downloaded <= 0:
            raise ValueError(f"HTTP {code}; downloaded {downloaded} bytes")
        result = {"type": "http", "tool": "curl/Cloudflare", "size": label,
                  "bytes": int(downloaded), "download_mbps": round(speed, 3),
                  "seconds": round(seconds, 3), "timestamp": now()}
        print(f"  {speed:.1f} Mbit/s | {seconds:.1f} sec", flush=True)
        return result
    except Exception as exc:
        print(f"  [ERROR] {exc}", flush=True)
        return None


def http_tests():
    results = []
    for label, size in HTTP_SIZES:
        for i in range(ROUNDS):
            item = curl_download(label, size)
            if item:
                results.append(item)
            if i + 1 < ROUNDS:
                time.sleep(2)
    return results


def iperf_test(server, reverse=False):
    direction = "download" if reverse else "upload"
    print(f"[IPERF3] {server['host']}:{server['port']} {direction}", flush=True)
    command = ["iperf3", "-c", server["host"], "-p", str(server["port"]),
               "-t", str(IPERF_SECONDS), "-P", str(IPERF_STREAMS), "-J"]
    if reverse:
        command.append("-R")
    try:
        data = json.loads(run(command, timeout=IPERF_SECONDS + 45).stdout)
        end = data.get("end", {})
        summary = end.get("sum_received") or end.get("sum")
        if not summary:
            raise ValueError("No throughput summary in iperf3 JSON")
        speed = mbps(summary["bits_per_second"])
        item = {"type": "iperf3", "tool": "iperf3", "host": server["host"],
                "port": server["port"], "region": server.get("region"),
                "direction": direction, "download_mbps": speed if reverse else None,
                "upload_mbps": None if reverse else speed, "timestamp": now()}
        print(f"  {speed:.1f} Mbit/s", flush=True)
        return item
    except Exception as exc:
        print(f"  [ERROR] {exc}", flush=True)
        return None


def iperf_tests():
    if not shutil.which("iperf3"):
        print("[SKIP] iperf3 not installed")
        return []
    results = []
    for server in IPERF_SERVERS:
        for i in range(ROUNDS):
            for reverse in (False, True):
                item = iperf_test(server, reverse)
                if item:
                    results.append(item)
            time.sleep(2)
    return results


def stats(values):
    if not values:
        return None
    return {"samples": len(values), "mean_mbps": round(statistics.mean(values), 2),
            "median_mbps": round(statistics.median(values), 2),
            "p10_mbps": round(percentile(values, 10), 2), "min_mbps": round(min(values), 2),
            "max_mbps": round(max(values), 2),
            "stdev_mbps": round(statistics.stdev(values), 2) if len(values) > 1 else 0}


def main():
    if ROUNDS < 1 or USER_MBPS <= 0 or not 0 < SAFETY_FACTOR <= 1:
        raise SystemExit("ROUNDS must be >= 1, USER_MBPS > 0, SAFETY_FACTOR in (0, 1]")
    print("VPS NETWORK BENCHMARK", flush=True)
    print(f"Start: {now()} | rounds={ROUNDS} | user={USER_MBPS:g} Mbit/s", flush=True)
    results = []
    results += speedtest_ookla()
    results += speedtest_python()
    results += http_tests()
    results += iperf_tests()

    groups = {
        "speedtest_download": [r["download_mbps"] for r in results if r["type"] == "speedtest"],
        "speedtest_upload": [r["upload_mbps"] for r in results if r["type"] == "speedtest"],
        "http_download": [r["download_mbps"] for r in results if r["type"] == "http"],
        "iperf_download": [r["download_mbps"] for r in results if r["type"] == "iperf3" and r["direction"] == "download"],
        "iperf_upload": [r["upload_mbps"] for r in results if r["type"] == "iperf3" and r["direction"] == "upload"],
    }
    summary = {name: stats(values) for name, values in groups.items()}

    # Compare family medians, not every raw sample. HTTP is download-only.
    down_families = [summary[k]["median_mbps"] for k in ("speedtest_download", "http_download", "iperf_download") if summary[k]]
    up_families = [summary[k]["median_mbps"] for k in ("speedtest_upload", "iperf_upload") if summary[k]]
    down = min(down_families) if down_families else None
    up = min(up_families) if up_families else None
    bottleneck = min(down, up) if down is not None and up is not None else None
    capacity = None
    if bottleneck is not None:
        usable = bottleneck * SAFETY_FACTOR
        capacity = {"download_capacity_mbps": round(down, 2), "upload_capacity_mbps": round(up, 2),
                    "bottleneck_mbps": round(bottleneck, 2), "usable_mbps": round(usable, 2),
                    "theoretical_users_at_configured_rate": math.floor(bottleneck / USER_MBPS),
                    "estimated_users_at_configured_rate": math.floor(usable / USER_MBPS)}

    report = {"started_at": now(), "config": {"rounds": ROUNDS, "iperf_seconds": IPERF_SECONDS,
              "iperf_streams": IPERF_STREAMS, "user_mbps": USER_MBPS,
              "safety_factor": SAFETY_FACTOR, "http_sizes_bytes": [n for _, n in HTTP_SIZES]},
              "statistics": summary, "capacity_estimate": capacity, "results": results}
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n========== SUMMARY ==========")
    for name, value in summary.items():
        print(f"{name}: {value}")
    print(f"capacity_estimate: {capacity}")
    print(f"JSON report: {RESULT_FILE}")
    if not results:
        raise SystemExit("No tests succeeded; inspect network access and logs")


if __name__ == "__main__":
    main()
