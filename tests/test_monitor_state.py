"""The monitor service keeps its policy state in S3 between daily calls. A drift streak
must survive across calls, or persistent drift can never raise an alarm."""

from pathlib import Path

import pandas as pd

from fml.features.definitions import FEATURES
from fml.monitor import service
from fml.policy import PolicyState


def test_drift_streak_survives_between_daily_checks(monkeypatch):
    store: dict[str, object] = {}
    monkeypatch.setattr(service.storage, "exists", lambda k: k in store)
    monkeypatch.setattr(service.storage, "get_json", lambda k: store[k])
    monkeypatch.setattr(service.storage, "put_json", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(service.storage, "put_bytes", lambda *a, **k: None)
    monkeypatch.setattr(service.registry, "resolve_version", lambda ref: "1")
    monkeypatch.setattr(
        service.registry,
        "version_tags",
        lambda v: {"live_from_day": "36", "holdout_recall_at_budget": "0.8"},
    )
    monkeypatch.setattr(service, "_reference", lambda v: pd.DataFrame())
    row = {f: 0.0 for f in FEATURES} | {
        "day": 60,
        "score": 0.1,
        "model_version": "1",
        "txn_id": 1,
        "amount": 1.0,
    }
    monkeypatch.setattr(service, "read_predictions", lambda *a, **k: pd.DataFrame([row]))
    monkeypatch.setattr(service, "read_labels", lambda *a, **k: pd.DataFrame({"txn_id": []}))

    def fake_drift(reference, current, html_path=None):
        Path(html_path).write_text("<html></html>")
        return {
            "drift_share": 1 / 12,
            "drifted_features": ["category_code"],
            "feature_scores": {"category_code": 0.12},
            "prediction_drift": 0.0,
        }

    monkeypatch.setattr(service, "drift_report", fake_drift)
    submitted = []
    monkeypatch.setattr(
        service.k8s,
        "submit_retrain",
        lambda run, day, seed, reason: submitted.append(day) or f"wf-{day}",
    )
    monkeypatch.setattr(service.events, "emit", lambda *a, **k: None)
    store["runs/r/monitor/state.json"] = PolicyState(last_attempt_day=35).__dict__

    results = [service.check(service.RunRequest(run="r", day=d)) for d in (60, 61, 62)]

    assert [r["retrain"] for r in results] == [False, False, True]
    assert submitted == [62]
