"""Timeline events. Each event is its own S3 object; `fml collect` merges them."""

from __future__ import annotations

import time
import uuid

from fml import storage

TYPES = {
    "run_started",
    "day_completed",
    "drift_detected",
    "retrain_started",
    "parity_checked",
    "challenger_trained",
    "gate_passed",
    "gate_failed",
    "canary_step",
    "promoted",
    "rolled_back",
    "run_finished",
}


def emit(run: str, day: int, type_: str, source: str, details: str = "", **extra) -> dict:
    if type_ not in TYPES:
        raise ValueError(f"unknown event type {type_!r}")
    now = time.time()
    event = {
        "day": day,
        "real_time": round(now, 3),
        "type": type_,
        "source": source,
        "details": details,
        **extra,
    }
    key = f"runs/{run}/events/{int(now * 1000):013d}-{source}-{uuid.uuid4().hex[:8]}.json"
    storage.put_json(key, event)
    return event


def collect(run: str) -> list[dict]:
    keys = sorted(storage.list_keys(f"runs/{run}/events/"))
    events = [storage.get_json(k) for k in keys]
    return sorted(events, key=lambda e: (e["day"], e["real_time"]))
