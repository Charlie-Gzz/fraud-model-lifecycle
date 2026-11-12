"""Traffic replay: the clock of a full-loop run. Runs as a Job inside the cluster.

For each simulated day it sends that day's transactions to the scorer, publishes the
fraud reports that "arrive" that day, and asks the monitor to check the day. While a
canary is in progress it slows down, so the canary analysis sees steady traffic.

Usage: python -m fml.replay.run --scenario test/new_fraud_pattern --seed 201 --run RUN
"""

from __future__ import annotations

import argparse
import contextlib
import threading
import time

import httpx
import pandas as pd

from fml import events, k8s, lifecycle, storage
from fml.data import generator, scenarios
from fml.pipeline import rollout

SCORER = "http://fraud-scorer.fml.svc.cluster.local/score_batch"
MONITOR = "http://fml-monitor.fml.svc.cluster.local"
TXN_FIELDS = ["txn_id", "ts", "user_id", "merchant_id", "category", "device_id", "amount"]
FLUSH_WAIT_S = 5  # scorer pods flush their prediction logs every 3 s


def _post(client: httpx.Client, url: str, payload: dict, tries: int = 20) -> httpx.Response:
    """POST with retries. Safe to retry: online features ignore rows at or after `ts`."""
    for i in range(tries):
        try:
            resp = client.post(url, json=payload)
            if resp.status_code < 500:
                return resp
        except httpx.HTTPError:
            pass
        time.sleep(min(0.2 * (i + 1), 2))
    raise RuntimeError(f"{url} kept failing")


def send_day(run: str, day_df: pd.DataFrame, shards: int, batch: int, rate: float | None) -> dict:
    """Send a day's traffic. Users are split across shards so each user stays in order."""
    stats = {"requests": 0, "errors": 0}
    lock = threading.Lock()

    def worker(part: pd.DataFrame) -> None:
        # No keep-alive: each request opens a new connection, so kube-proxy spreads
        # traffic across stable and canary pods in proportion to their count.
        with httpx.Client(timeout=30, limits=httpx.Limits(max_keepalive_connections=0)) as c:
            rows = part[TXN_FIELDS].to_dict("records")
            for i in range(0, len(rows), batch):
                t0 = time.time()
                _post(c, SCORER, {"run": run, "transactions": rows[i : i + batch]})
                with lock:
                    stats["requests"] += 1
                if rate:  # throttle to `rate` transactions per second overall
                    time.sleep(max(0.0, shards * batch / rate - (time.time() - t0)))

    threads = [
        threading.Thread(target=worker, args=(day_df[day_df.user_id % shards == s],))
        for s in range(shards)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return stats


def reset_service() -> None:
    """Start every run from scratch: empty online state, no champion, warm-up scorer."""
    import redis

    from fml.serve import registry

    redis.Redis.from_url("redis://redis.fml.svc.cluster.local:6379/0").flushdb()
    for alias in (registry.CHAMPION, registry.CHALLENGER):
        with contextlib.suppress(Exception):
            registry.client().delete_registered_model_alias(registry.MODEL_NAME, alias)
    rollout.reset("none")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--policy", default="drift")
    ap.add_argument("--shards", type=int, default=4)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--canary-rate", type=float, default=25.0, help="txns/s during a canary")
    ap.add_argument("--days", type=int, default=None)
    args = ap.parse_args()

    sc = scenarios.load(args.scenario)
    df = generator.generate(sc, args.seed)
    n_days = args.days or sc.n_days
    reset_service()
    events.emit(
        args.run,
        0,
        "run_started",
        "replay",
        f"{sc.key} seed {args.seed}",
        scenario=sc.key,
        seed=args.seed,
        policy=args.policy,
        drift_start=sc.drift_start,
    )
    pending: str | None = None  # workflow whose canary may still be running

    with httpx.Client(timeout=300) as mon:
        for d in range(n_days):
            t0 = time.time()
            canary = pending is not None and k8s.workflow_phase(pending) == "Running"
            day_df = df[df.day == d]
            stats = send_day(
                args.run,
                day_df,
                args.shards,
                args.batch if not canary else 10,
                args.canary_rate if canary else None,
            )
            time.sleep(FLUSH_WAIT_S)
            fraud = df[(df.is_fraud == 1) & (df.report_day == d)][["txn_id", "report_day"]]
            storage.put_df(f"runs/{args.run}/labels/day={d:03d}.parquet", fraud)
            if pending is not None:
                phase = k8s.wait_workflow(pending)
                print(f"  workflow {pending}: {phase}")
                pending = None

            note = ""
            if d == lifecycle.FIRST_TRAIN_DAY:
                wf = k8s.submit_retrain(args.run, d, args.seed, "bootstrap")
                _post(mon, f"{MONITOR}/attempt", {"run": args.run, "day": d})
                events.emit(
                    args.run,
                    d,
                    "retrain_started",
                    "replay",
                    "bootstrap: first model from the settled weeks",
                    workflow=wf,
                )
                note = f"bootstrap workflow {wf}: {k8s.wait_workflow(wf)}"
            elif d > lifecycle.FIRST_TRAIN_DAY and args.policy != "none":
                res = _post(
                    mon,
                    f"{MONITOR}/run",
                    {"run": args.run, "day": d, "seed": args.seed, "policy": args.policy},
                ).json()
                note = res.get("decision", res.get("reason", ""))
                if res.get("workflow"):
                    pending = res["workflow"]
                    phase = k8s.wait_workflow(pending, until_step="canary-rollout")
                    note += f" -> {pending} ({phase})"
                    if phase != "Running":
                        pending = None
            events.emit(
                args.run,
                d,
                "day_completed",
                "replay",
                note,
                n=len(day_df),
                n_fraud=int(day_df.is_fraud.sum()),
                requests=stats["requests"],
                canary=canary,
                seconds=round(time.time() - t0, 1),
            )
            print(
                f"day {d:3d}: {len(day_df):5d} txns, {stats['requests']:4d} requests, "
                f"{time.time() - t0:5.1f}s {'[canary pace] ' if canary else ''}{note}",
                flush=True,
            )
    events.emit(args.run, n_days - 1, "run_finished", "replay", "replay complete")


if __name__ == "__main__":
    main()
