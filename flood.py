#!/usr/bin/env python3
"""Aggressive HTTP load test without rate limiter. For stress testing only."""

from __future__ import annotations

import argparse
import os
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

REQUEST_TIMEOUT_SECONDS = 2
REPORT_INTERVAL_SECONDS = 3
MAX_DURATION_SECONDS = 300
MAX_CONCURRENCY = 2000


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--path", default="/")
    return parser.parse_args()


def request_status(opener, host, port, path):
    request = urllib.request.Request(f"http://{host}:{port}{path}", method="GET")
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return str(response.status)
    except urllib.error.HTTPError as error:
        return str(error.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return "000"


def worker(host, port, path, deadline, stop_event, counts, counts_lock):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while not stop_event.is_set() and time.monotonic() < deadline:
        code = request_status(opener, host, port, path)
        with counts_lock:
            counts[code] += 1


def snapshot(counts, lock):
    with lock:
        return counts.copy()


def report(label, counts, final=False):
    total = sum(counts.values())
    ok = counts["200"]
    failed = total - ok
    tag = "RESULT" if final else f"[{datetime.now():%H:%M:%S}]"
    print(f"  {tag} {label}: total={total} ok(200)={ok} failed={failed}", flush=True)
    if final and total:
        print(f"  -> {failed * 100 // total}% non-200", flush=True)


def main():
    args = parse_args()
    duration = int(os.environ.get("DURATION", "20"))
    concurrency = int(os.environ.get("CONCURRENCY", "100"))
    label = f"{args.host}:{args.port}{args.path}"

    print(f"=== BRUTE MODE: {concurrency} workers, {duration}s, {label} ===", flush=True)

    counts = Counter()
    counts_lock = threading.Lock()
    stop_event = threading.Event()
    deadline = time.monotonic() + duration

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(worker, args.host, args.port, args.path,
                            deadline, stop_event, counts, counts_lock)
            for _ in range(concurrency)
        ]
        try:
            while time.monotonic() < deadline:
                time.sleep(min(REPORT_INTERVAL_SECONDS, deadline - time.monotonic()))
                report(label, snapshot(counts, counts_lock))
        except KeyboardInterrupt:
            stop_event.set()
        finally:
            stop_event.set()
        for f in futures:
            f.result()

    report(label, snapshot(counts, counts_lock), final=True)


if __name__ == "__main__":
    main()