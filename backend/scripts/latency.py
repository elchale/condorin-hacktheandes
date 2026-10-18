"""Light latency probe: p50 and p95 of a few GET routes, optionally with concurrent clients.

    python scripts/latency.py https://api.condorin.pe /healthz/ / --n 20
    python scripts/latency.py http://127.0.0.1:8000 /api/v1/mapa --n 40 --concurrency 10

Read only (GET). Prints one line per route: status codes, p50, p95, max, and body bytes with and
without gzip. Keep --n small against production.
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import requests


def timed_get(session: requests.Session, url: str) -> tuple[float, int]:
    start = time.perf_counter()
    resp = session.get(url, timeout=30)
    return (time.perf_counter() - start) * 1000, resp.status_code


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def probe(base: str, path: str, n: int, concurrency: int) -> str:
    url = base.rstrip('/') + path
    raw = requests.get(url, headers={'Accept-Encoding': 'identity'}, timeout=30)
    gz = requests.get(url, headers={'Accept-Encoding': 'gzip'}, stream=True, timeout=30)
    gz_bytes = len(gz.raw.read(decode_content=False))
    sessions = [requests.Session() for _ in range(concurrency)]
    with ThreadPoolExecutor(concurrency) as pool:
        results = list(pool.map(lambda i: timed_get(sessions[i % concurrency], url), range(n)))
    times = [t for t, _ in results]
    codes = sorted({c for _, c in results})
    return (f'{path:<16} c={concurrency:<3} n={n:<4} codes={codes} p50={statistics.median(times):7.1f}ms '
            f'p95={pct(times, 0.95):7.1f}ms max={max(times):7.1f}ms raw={len(raw.content)}B '
            f'gzip={gz_bytes}B ({gz.headers.get("Content-Encoding", "none")})')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('base')
    parser.add_argument('paths', nargs='+')
    parser.add_argument('--n', type=int, default=20)
    parser.add_argument('--concurrency', type=int, default=1)
    args = parser.parse_args()
    for path in args.paths:
        print(probe(args.base, path, args.n, args.concurrency), flush=True)


if __name__ == '__main__':
    main()
