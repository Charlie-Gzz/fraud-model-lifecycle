"""Build the Grafana dashboard JSON and write it into k8s/dashboard.yaml as a ConfigMap.

Run: uv run python -m fml.viz.grafana
"""

from __future__ import annotations

import json

import yaml

from fml import REPO_ROOT
from fml.viz.theme import ACCENT, ALERT, CHALLENGER, HEALTHY, WARN

DS = {"type": "prometheus", "uid": "prometheus"}


def _target(expr: str, legend: str = "", ref: str = "A") -> dict:
    return {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref}


def stat(title, expr, x, unit="none", decimals=None, thresholds=None, mappings=None, w=5):
    return {
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": 0, "w": w, "h": 5},
        "targets": [_target(expr)],
        "options": {
            "colorMode": "background",
            "graphMode": "area",
            "textMode": "value",
            "reduceOptions": {"calcs": ["lastNotNull"]},
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": decimals,
                "mappings": mappings or [],
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": thresholds or [{"color": ACCENT, "value": None}],
                },
            },
            "overrides": [],
        },
    }


def series(title, targets, x, y, w=12, h=8, unit="none", colors=None, max_=None):
    overrides = [
        {
            "matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}],
        }
        for name, c in (colors or {}).items()
    ]
    return {
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [_target(e, leg, chr(65 + i)) for i, (e, leg) in enumerate(targets)],
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi"},
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "max": max_,
                "color": {"mode": "palette-classic"},
                "custom": {"lineWidth": 2, "fillOpacity": 8, "showPoints": "never"},
            },
            "overrides": overrides,
        },
    }


def dashboard() -> dict:
    drift_steps = [{"color": HEALTHY, "value": None}, {"color": ALERT, "value": 1}]
    panels = [
        stat("Requests / sec", "sum(rate(fml_requests_total[1m]))", 0, "reqps", 1),
        stat(
            "p95 latency",
            "histogram_quantile(0.95, sum by (le) (rate(fml_request_latency_seconds_bucket[1m])))",
            5,
            "s",
            3,
        ),
        stat(
            "Flag rate",
            "sum(rate(fml_flagged_total[5m])) / sum(rate(fml_predictions_total[5m]))",
            10,
            "percentunit",
            2,
            [
                {"color": HEALTHY, "value": None},
                {"color": WARN, "value": 0.02},
                {"color": ALERT, "value": 0.03},
            ],
        ),
        stat("Champion version", "max(fml_champion_version)", 15, "none", 0),
        stat(
            "Drift status",
            "max(fml_drift_alarm)",
            20,
            "none",
            0,
            drift_steps,
            [{"type": "value", "options": {"0": {"text": "OK"}, "1": {"text": "DRIFT"}}}],
            w=4,
        ),
        series(
            "Requests / sec by model version",
            [("sum by (model_version) (rate(fml_requests_total[1m]))", "v{{model_version}}")],
            0,
            5,
            unit="reqps",
        ),
        series(
            "Flag rate by model version (budget 1%)",
            [
                (
                    "sum by (model_version) (rate(fml_flagged_total[2m])) / sum by (model_version)"
                    " (rate(fml_predictions_total[2m]))",
                    "v{{model_version}}",
                )
            ],
            12,
            5,
            unit="percentunit",
        ),
        series(
            "Share of features drifting (alarm: any feature, 3 days in a row)",
            [("max(fml_drift_share)", "drifted features")],
            0,
            13,
            unit="percentunit",
            colors={"drifted features": WARN},
            max_=1,
        ),
        series(
            "Recall at the alert budget, settled labels only",
            [("max(fml_delayed_recall)", "recall"), ("max(fml_delayed_pr_auc)", "PR-AUC")],
            12,
            13,
            unit="percentunit",
            colors={"recall": ACCENT, "PR-AUC": CHALLENGER},
            max_=1,
        ),
        series(
            "Drift score per feature and of the model score (threshold 0.1)",
            [
                ("max by (feature) (fml_feature_drift)", "{{feature}}"),
                ("max(fml_prediction_drift)", "model score"),
            ],
            0,
            21,
            w=12,
        ),
        series(
            "Latency p50 / p95",
            [
                (
                    "histogram_quantile(0.5, sum by (le) (rate(fml_request_latency_seconds_bucket"
                    "[1m])))",
                    "p50",
                ),
                (
                    "histogram_quantile(0.95, sum by (le) (rate(fml_request_latency_seconds_bucket"
                    "[1m])))",
                    "p95",
                ),
            ],
            12,
            21,
            unit="s",
        ),
        series(
            "Scorer pods by template (canary vs stable)",
            [
                (
                    "count by (rollouts_pod_template_hash) (fml_model_info)",
                    "{{rollouts_pod_template_hash}}",
                )
            ],
            0,
            29,
            w=12,
        ),
        series(
            "Simulated day",
            [("max(fml_sim_day)", "served"), ("max(fml_monitor_day)", "monitored")],
            12,
            29,
        ),
    ]
    for i, p in enumerate(panels):
        p["id"] = i + 1
    return {
        "uid": "fraud-lifecycle",
        "title": "Tideline: fraud model lifecycle",
        "tags": ["fml"],
        "timezone": "utc",
        "schemaVersion": 39,
        "editable": False,
        "time": {"from": "now-30m", "to": "now"},
        "refresh": "10s",
        "panels": panels,
    }


def write() -> None:
    cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "fml-dashboard",
            "labels": {"grafana_dashboard": "1", "project": "fraud-model-lifecycle"},
        },
        "data": {"fraud-lifecycle.json": json.dumps(dashboard(), indent=1)},
    }
    out = REPO_ROOT / "k8s" / "dashboard.yaml"
    out.write_text(
        "# Generated by `python -m fml.viz.grafana`. Do not edit by hand.\n"
        + yaml.safe_dump(cm, sort_keys=False, width=120)
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    write()
