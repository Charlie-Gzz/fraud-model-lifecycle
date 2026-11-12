"""The fraud scoring service.

- loads one model version at startup (MODEL_VERSION, or the `champion` alias)
- computes online features from Redis for each transaction
- exposes Prometheus metrics (latency, errors, scores, flag rate) per model version
- logs every request, its online features and its score to S3 for the drift monitor

With no model registered yet it runs in warm-up mode: features are computed and logged
(so the first training run has data), but nothing is scored.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
import pandas as pd
import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

from fml import storage
from fml.features.definitions import DAY, FEATURES
from fml.features.online import OnlineFeatures
from fml.serve import registry

POD = os.environ.get("POD_NAME", "local")
FLUSH_ROWS, FLUSH_SECONDS = 5000, 3.0

REQUESTS = Counter(
    "fml_requests_total", "Scoring requests", ["endpoint", "status", "model_version"]
)
LATENCY = Histogram(
    "fml_request_latency_seconds",
    "Request latency",
    ["endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)
PREDICTIONS = Counter("fml_predictions_total", "Transactions scored", ["model_version"])
FLAGGED = Counter("fml_flagged_total", "Transactions flagged for review", ["model_version"])
SCORES = Histogram(
    "fml_score",
    "Model scores",
    ["model_version"],
    buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 0.8, 1.0),
)
MODEL_INFO = Gauge("fml_model_info", "Model version loaded by this pod", ["model_version"])
SIM_DAY = Gauge("fml_sim_day", "Latest simulated day seen by this pod")


class Txn(BaseModel):
    txn_id: int
    ts: int
    user_id: int
    merchant_id: int
    category: str | int
    device_id: int
    amount: float


class Batch(BaseModel):
    run: str = "adhoc"
    transactions: list[Txn]


class PredictionLog:
    """Buffers rows and writes Parquet chunks to S3, partitioned by simulated day."""

    def __init__(self):
        self.rows: list[dict] = []
        self.lock = threading.Lock()
        self.flush_lock = threading.Lock()  # one writer at a time, so keys never collide
        self.seq = 0
        self.last_flush = time.time()
        threading.Thread(target=self._loop, daemon=True).start()

    def add(self, rows: list[dict]) -> None:
        with self.lock:
            self.rows.extend(rows)
            full = len(self.rows) >= FLUSH_ROWS
        if full:
            self.flush()

    def _loop(self) -> None:
        while True:
            time.sleep(1.0)
            if time.time() - self.last_flush >= FLUSH_SECONDS:
                self.flush()

    def flush(self) -> None:
        with self.flush_lock:
            with self.lock:
                rows, self.rows = self.rows, []
                self.last_flush = time.time()
            if not rows:
                return
            df = pd.DataFrame(rows)
            for (run, day), part in df.groupby(["run", "day"]):
                self.seq += 1
                key = f"runs/{run}/predictions/day={int(day):03d}/{POD}-{self.seq:06d}.parquet"
                storage.put_df(key, part.drop(columns=["run"]))


class Scorer:
    def __init__(self):
        self.features = OnlineFeatures(
            redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
        )
        self.log = PredictionLog()
        self.model = None
        version = registry.resolve_version(os.environ.get("MODEL_VERSION"))
        if version:
            self.model = registry.load(version)
            if self.model.features != FEATURES:
                # Kept on purpose: a schema mismatch must fail loudly at predict time
                # (and be caught by the canary), not be silently "fixed" here.
                print(f"WARNING: model v{version} expects {len(self.model.features)} features")
        self.version = self.model.version if self.model else "none"
        MODEL_INFO.labels(self.version).set(1)

    def score(self, run: str, txns: list[Txn]) -> list[dict]:
        records = [t.model_dump() for t in txns]
        feats = self.features.compute_and_update(records)
        X = pd.DataFrame(feats)[FEATURES]
        if self.model is None:
            scores = np.full(len(X), np.nan)
            flagged = np.zeros(len(X), dtype=bool)
        else:
            scores = self.model.booster.predict(X[self.model.features])
            flagged = scores >= self.model.threshold
            PREDICTIONS.labels(self.version).inc(len(X))
            FLAGGED.labels(self.version).inc(int(flagged.sum()))
            for s in scores:
                SCORES.labels(self.version).observe(float(s))
        SIM_DAY.set(max(r["ts"] for r in records) // DAY)
        rows = []
        for rec, f, s, fl in zip(records, feats, scores, flagged, strict=True):
            rows.append(
                {
                    **rec,
                    "category": str(rec["category"]),
                    **f,
                    "score": float(s),
                    "flagged": bool(fl),
                    "model_version": self.version,
                    "pod": POD,
                    "run": run,
                    "day": rec["ts"] // DAY,
                }
            )
        self.log.add(rows)
        return [
            {
                "txn_id": r["txn_id"],
                "score": None if np.isnan(r["score"]) else r["score"],
                "flagged": r["flagged"],
                "model_version": self.version,
            }
            for r in rows
        ]


scorer: Scorer | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global scorer
    scorer = Scorer()
    yield
    scorer.log.flush()


app = FastAPI(title="fraud-scorer", lifespan=lifespan)


def _handle(endpoint: str, run: str, txns: list[Txn]) -> list[dict]:
    start = time.perf_counter()
    try:
        out = scorer.score(run, txns)
        REQUESTS.labels(endpoint, "ok", scorer.version).inc()
        return out
    except Exception as exc:
        REQUESTS.labels(endpoint, "error", scorer.version).inc()
        raise HTTPException(status_code=500, detail=f"scoring failed: {exc}") from exc
    finally:
        LATENCY.labels(endpoint).observe(time.perf_counter() - start)


@app.post("/score")
def score_one(txn: Txn, run: str = "adhoc") -> dict:
    return _handle("score", run, [txn])[0]


@app.post("/score_batch")
def score_batch(batch: Batch) -> list[dict]:
    return _handle("score_batch", batch.run, batch.transactions)


@app.post("/flush")
def flush() -> dict:
    scorer.log.flush()
    return {"flushed": True}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "model_version": scorer.version if scorer else "loading"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
