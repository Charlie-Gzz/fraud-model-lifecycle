"""In-cluster load generator: steady traffic for canary tests and a latency/throughput
measurement. Runs as a Job; prints one JSON line of stats at the end.

Usage: python -m fml.replay.load --seconds 240 --workers 8 [--rate 40]
"""

from __future__ import annotations

import argparse
import json
import threading
import time

import httpx
import numpy as np

from fml.data import generator, scenarios
from fml.replay.run import TXN_FIELDS

SCORER = "http://fraud-scorer.fml.svc.cluster.local/score"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rate", type=float, default=None, help="max requests/s overall")
    ap.add_argument("--run", default="loadtest")
    args = ap.parse_args()

    sc = scenarios.load("dev/control")
    df = generator.generate(sc, 7)
    df = df[df.day >= 40]
    latencies, errors, lock = [], [0], threading.Lock()
    end = time.time() + args.seconds

    def worker(w: int) -> None:
        part = df[df.user_id % args.workers == w][TXN_FIELDS].to_dict("records")
        i = 0
        with httpx.Client(timeout=10, limits=httpx.Limits(max_keepalive_connections=0)) as c:
            while time.time() < end and i < len(part):
                t0 = time.perf_counter()
                try:
                    ok = c.post(SCORER, params={"run": args.run}, json=part[i]).status_code < 500
                except httpx.HTTPError:
                    ok = False
                dt = time.perf_counter() - t0
                with lock:
                    latencies.append(dt)
                    errors[0] += 0 if ok else 1
                i += 1
                if args.rate:
                    time.sleep(max(0.0, args.workers / args.rate - dt))

    started = time.time()
    threads = [threading.Thread(target=worker, args=(w,)) for w in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    took = time.time() - started
    lat = np.array(latencies) * 1000
    print(
        json.dumps(
            {
                "requests": len(lat),
                "errors": errors[0],
                "seconds": round(took, 1),
                "throughput_rps": round(len(lat) / took, 1),
                "workers": args.workers,
                "p50_ms": round(float(np.percentile(lat, 50)), 1),
                "p95_ms": round(float(np.percentile(lat, 95)), 1),
                "p99_ms": round(float(np.percentile(lat, 99)), 1),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
