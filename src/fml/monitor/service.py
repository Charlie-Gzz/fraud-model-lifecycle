"""Drift monitor service.

At the end of each simulated day the replay calls POST /run. The monitor then:
1. measures delayed-label performance on settled days (labels known by today only)
2. runs Evidently data + prediction drift: champion's training reference vs last week
3. stores the JSON result and the HTML report in S3, updates Prometheus gauges
4. asks the retraining policy; on "retrain" it submits the Argo Workflow

In a real deployment a CronJob would call /run on a schedule; in the simulation the
replay is the clock.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel

from fml import events, k8s, lifecycle, storage
from fml.features.definitions import FEATURES
from fml.monitor.drift import drift_report
from fml.pipeline.steps import read_labels, read_predictions
from fml.policy import PolicyState, after_retrain, decide, load_config
from fml.serve import registry
from fml.train import model as M

DRIFT_SHARE = Gauge("fml_drift_share", "Share of features with data drift")
FEATURE_DRIFT = Gauge("fml_feature_drift", "Drift score per feature", ["feature"])
PRED_DRIFT = Gauge("fml_prediction_drift", "Drift score of the model's score distribution")
DELAYED_RECALL = Gauge("fml_delayed_recall", "Recall at the alert budget on settled labels")
DELAYED_PR_AUC = Gauge("fml_delayed_pr_auc", "PR-AUC on settled labels")
ALARM = Gauge("fml_drift_alarm", "1 when the monitor raises a drift or performance alarm")
MONITOR_DAY = Gauge("fml_monitor_day", "Last simulated day the monitor checked")
CHAMPION = Gauge("fml_champion_version", "Model version currently serving as champion")
RETRAINS = Counter("fml_retrains_total", "Retraining workflows submitted", ["reason"])

app = FastAPI(title="fml-monitor")
_reference_cache: dict[str, pd.DataFrame] = {}


class RunRequest(BaseModel):
    run: str
    day: int
    seed: int = 0
    policy: str = "drift"


def _reference(version: str) -> pd.DataFrame:
    if version not in _reference_cache:
        import mlflow

        with tempfile.TemporaryDirectory() as tmp:
            path = mlflow.artifacts.download_artifacts(
                artifact_uri=f"models:/{registry.MODEL_NAME}/{version}/reference.parquet",
                dst_path=tmp,
            )
            _reference_cache[version] = pd.read_parquet(path)
    return _reference_cache[version]


def _state(run: str) -> PolicyState:
    key = f"runs/{run}/monitor/state.json"
    raw = storage.get_json(key) if storage.exists(key) else {"last_attempt_day": -1}
    return PolicyState(**raw)


def _save_state(run: str, state: PolicyState) -> None:
    storage.put_json(f"runs/{run}/monitor/state.json", state.__dict__)


def check(req: RunRequest) -> dict:
    d = req.day
    params = load_config()["policies"][req.policy]
    version = registry.resolve_version(registry.CHAMPION)
    if version is None:
        return {"day": d, "retrain": False, "reason": "no champion yet"}
    tags = registry.version_tags(version)
    live_from = int(tags.get("live_from_day", d))
    champion_recall = float(tags["holdout_recall_at_budget"])
    CHAMPION.set(int(version))

    perf_lo, perf_hi = lifecycle.performance_window(d)
    mon_lo, mon_hi = lifecycle.monitor_window(d)
    pred = read_predictions(req.run, d, min_day=min(perf_lo, mon_lo))
    out: dict = {"day": d, "champion_version": version}

    perf = pred[
        pred["day"].between(max(perf_lo, lifecycle.FIRST_TRAIN_DAY + 1), perf_hi)
        & pred["score"].notna()
    ]
    if len(perf):
        labels = read_labels(req.run, d)
        y = perf["txn_id"].isin(set(labels["txn_id"])).to_numpy().astype(np.int8)
        m = M.evaluate(
            perf["score"].to_numpy(), y, perf["day"].to_numpy(), perf["amount"].to_numpy()
        )
        out["delayed_recall"], out["delayed_pr_auc"] = m["recall_at_budget"], m["pr_auc"]
        DELAYED_RECALL.set(m["recall_at_budget"])
        DELAYED_PR_AUC.set(m["pr_auc"])

    lo = max(mon_lo, live_from)
    cur = pred[pred["day"].between(lo, mon_hi) & (pred["model_version"] == version)]
    if mon_hi - lo + 1 >= 3 and len(cur):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "report.html"
            drift = drift_report(_reference(version), cur[[*FEATURES, "score"]], html)
            report_key = f"runs/{req.run}/reports/day={d:03d}.html"
            storage.put_bytes(report_key, html.read_bytes(), "text/html")
        out.update(drift, report=report_key)
        DRIFT_SHARE.set(drift["drift_share"])
        PRED_DRIFT.set(drift["prediction_drift"])
        for f, v in drift["feature_scores"].items():
            FEATURE_DRIFT.labels(f).set(v)

    state = _state(req.run)
    dec = decide(req.policy, params, d, state, out, champion_recall)
    out.update(decision=dec.reason, alarms=list(dec.alarms), retrain=dec.retrain)
    ALARM.set(1 if dec.alarms else 0)
    MONITOR_DAY.set(d)
    if dec.alarms:
        events.emit(
            req.run,
            d,
            "drift_detected",
            "monitor",
            dec.reason,
            alarms=list(dec.alarms),
            feature_scores=out.get("feature_scores", {}),
            drift_share=out.get("drift_share"),
            report=out.get("report"),
            delayed_recall=out.get("delayed_recall"),
        )
    if dec.retrain:
        wf = k8s.submit_retrain(req.run, d, req.seed + d, dec.reason)
        out["workflow"] = wf
        after_retrain(state, dec, d, params)
        _save_state(req.run, state)
        RETRAINS.labels("drift").inc()
        events.emit(req.run, d, "retrain_started", "monitor", dec.reason, workflow=wf)
    storage.put_json(f"runs/{req.run}/monitor/day={d:03d}.json", out)
    return out


@app.post("/run")
def run(req: RunRequest) -> dict:
    return json.loads(json.dumps(check(req), default=float))


@app.post("/attempt")
def attempt(req: RunRequest) -> dict:
    """Record a retrain started outside the monitor (the bootstrap), for the cooldown."""
    _save_state(req.run, PolicyState(last_attempt_day=req.day))
    return {"ok": True}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
