"""Host side of a full-loop run: launch the replay Job, then collect its results.

`collect` turns the run's S3 objects into results/fullloop/{run}/:
  timeline.jsonl   every event (drift, retrain, gate, canary steps, promotions)
  daily.json       per-day fraud caught / PR-AUC from the served scores and the true labels,
                   plus the monitor's drift scores and delayed-label recall
  reports/         Evidently HTML reports for the days with drift alarms
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from fml import REPO_ROOT, events, storage
from fml.data import generator, scenarios
from fml.platform import env_for_python, kubectl
from fml.train import model as M

RESULTS = REPO_ROOT / "results" / "fullloop"


def _use_forwarded_services() -> None:
    env = env_for_python()
    os.environ.update({k: v for k, v in env.items() if k != "PATH"})
    os.environ["S3_ENDPOINT_URL"] = env["MLFLOW_S3_ENDPOINT_URL"]


def replay_job(run: str, scenario: str, seed: int, days: int | None, policy: str) -> dict:
    args = [
        "python",
        "-m",
        "fml.replay.run",
        "--scenario",
        scenario,
        "--seed",
        str(seed),
        "--run",
        run,
        "--policy",
        policy,
    ]
    if days:
        args += ["--days", str(days)]
    env = [
        {"name": "MLFLOW_TRACKING_URI", "value": "http://mlflow:5000"},
        {"name": "S3_ENDPOINT_URL", "value": "http://seaweedfs:8333"},
        {"name": "MLFLOW_S3_ENDPOINT_URL", "value": "http://seaweedfs:8333"},
    ]
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"replay-{run}"[:63].rstrip("-"),
            "namespace": "fml",
            "labels": {"project": "fraud-model-lifecycle", "app": "replay"},
        },
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 86400,
            "template": {
                "metadata": {"labels": {"project": "fraud-model-lifecycle", "app": "replay"}},
                "spec": {
                    "serviceAccountName": "fml-pipeline",
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "replay",
                            "image": "fml-runtime:0.1.0",
                            "imagePullPolicy": "Never",
                            "command": args,
                            "env": env,
                            "envFrom": [{"secretRef": {"name": "fml-secrets"}}],
                            "resources": {
                                "requests": {"cpu": "200m", "memory": "512Mi"},
                                "limits": {"memory": "1536Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }


def demo(scenario: str, seed: int, days: int | None = None, policy: str = "drift") -> str:
    stamp = datetime.now(UTC).strftime("%m%d%H%M")
    run = f"{scenario.replace('/', '-').replace('_', '-')}-s{seed}-{stamp}"
    job = replay_job(run, scenario, seed, days, policy)
    kubectl("apply", "-f", "-", input=json.dumps(job), quiet=True)
    name = job["metadata"]["name"]
    print(f"[fml] replay job {name} started (run {run})", flush=True)
    kubectl(
        "wait",
        "--for=condition=Ready",
        "pod",
        "-l",
        f"job-name={name}",
        "-n",
        "fml",
        "--timeout=300s",
        quiet=True,
    )
    kubectl("logs", "-f", f"job/{name}", "-n", "fml", check=False)
    while True:
        out = kubectl(
            "get",
            "job",
            name,
            "-n",
            "fml",
            "-o",
            "jsonpath={.status.succeeded}{.status.failed}",
            quiet=True,
        ).stdout
        if out.strip():
            break
        time.sleep(5)
    print(f"[fml] replay finished: {'ok' if out.strip() == '1' else 'FAILED'}")
    collect(run)
    return run


def _daily(run: str, df: pd.DataFrame) -> list[dict]:
    from fml.pipeline.steps import read_predictions

    pred = read_predictions(run, 10_000)
    truth = df.set_index("txn_id")
    pred = pred[pred["score"].notna()].copy()
    pred["is_fraud"] = truth.loc[pred["txn_id"], "is_fraud"].to_numpy()
    out = []
    monitor = {}
    for key in storage.list_keys(f"runs/{run}/monitor/day="):
        m = storage.get_json(key)
        monitor[int(m["day"])] = m
    for d, g in pred.groupby("day"):
        m = M.evaluate(
            g["score"].to_numpy(),
            g["is_fraud"].to_numpy(),
            g["day"].to_numpy(),
            g["amount"].to_numpy(),
        )
        versions = g["model_version"].value_counts().to_dict()
        mon = monitor.get(int(d), {})
        out.append(
            {
                "day": int(d),
                "recall": m["recall_at_budget"],
                "dollars_caught": m["dollars_caught"],
                "pr_auc": m["pr_auc"],
                "n_fraud": m["n_fraud"],
                "n": m["n"],
                "served_by": {str(k): int(v) for k, v in versions.items()},
                "monitor": {
                    k: mon[k]
                    for k in (
                        "drift_share",
                        "prediction_drift",
                        "delayed_recall",
                        "delayed_pr_auc",
                        "feature_scores",
                    )
                    if k in mon
                },
                "decision": mon.get("decision"),
            }
        )
    return out


def collect(run: str) -> None:
    _use_forwarded_services()
    out = RESULTS / run
    (out / "reports").mkdir(parents=True, exist_ok=True)
    evs = events.collect(run)
    start = next(e for e in evs if e["type"] == "run_started")
    sc = scenarios.load(start["scenario"])
    df = generator.generate(sc, start["seed"])
    daily = _daily(run, df)
    with (out / "timeline.jsonl").open("w") as f:
        for e in evs:
            f.write(json.dumps(e, default=float) + "\n")
    (out / "daily.json").write_text(json.dumps(daily, default=float))
    report_days = {e["day"] for e in evs if e["type"] == "drift_detected"}
    for d in sorted(report_days):
        key = f"runs/{run}/reports/day={d:03d}.html"
        if storage.exists(key):
            (out / "reports" / f"day{d:03d}.html").write_bytes(storage.get_bytes(key))
    for kind in ("gate", "train", "parity"):
        found = {}
        for key in storage.list_keys(f"runs/{run}/pipeline/"):
            if key.endswith(f"/{kind}.json"):
                found[key.split("/")[3]] = storage.get_json(key)
        (out / f"{kind}.json").write_text(json.dumps(found, indent=1, default=float))
    summary = {
        "run": run,
        "scenario": sc.key,
        "seed": start["seed"],
        "policy": start.get("policy"),
        "drift_start": sc.drift_start,
        "events": len(evs),
        "retrains": sum(e["type"] == "retrain_started" for e in evs),
        "promotions": sum(e["type"] == "promoted" for e in evs),
        "rollbacks": sum(e["type"] == "rolled_back" for e in evs),
        "days_served": len(daily),
        "mean_recall": float(np.nanmean([d["recall"] for d in daily])) if daily else None,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[fml] collected {len(evs)} events and {len(daily)} days into {out}")
    print(json.dumps(summary, indent=2))
