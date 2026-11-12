"""Build the static results site data (site/data/*.json) from saved results.

For each scenario the timeline comes from the full Kubernetes loop when a run exists
(results/fullloop/), else from the first backtest seed of the drift-triggered policy.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fml import REPO_ROOT
from fml.backtest.runner import RESULTS as BACKTEST
from fml.results import rolling
from fml.viz.charts import SCENARIO_LABEL

SITE = REPO_ROOT / "site"
FULLLOOP = REPO_ROOT / "results" / "fullloop"
KEEP_EVENTS = {
    "drift_detected",
    "retrain_started",
    "parity_checked",
    "challenger_trained",
    "gate_passed",
    "gate_failed",
    "canary_step",
    "promoted",
    "rolled_back",
}


def _latest_fullloop(set_name: str, scenario: str) -> Path | None:
    prefix = f"{set_name}-{scenario.replace('_', '-')}-s"
    runs = sorted(
        p
        for p in FULLLOOP.glob(f"{prefix}*")
        if (p / "daily.json").exists()
        and json.loads((p / "summary.json").read_text()).get("days_served", 0) > 60
    )
    return runs[-1] if runs else None


def _max_drift(mon: dict) -> float | None:
    fs = mon.get("feature_scores") or {}
    return max(fs.values()) if fs else None


def _from_fullloop(run_dir: Path, scenario: str) -> dict:
    daily = json.loads((run_dir / "daily.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    events = [json.loads(line) for line in (run_dir / "timeline.jsonl").read_text().splitlines()]
    roll = rolling(daily, 7)
    days = []
    for d in daily:
        mon = d.get("monitor", {})
        top = max(d["served_by"].items(), key=lambda kv: kv[1])[0] if d["served_by"] else None
        days.append(
            {
                "day": d["day"],
                "recall": roll.get(d["day"]),
                "recall_day": d["recall"],
                "delayed_pr_auc": mon.get("delayed_pr_auc"),
                "delayed_recall": mon.get("delayed_recall"),
                "drift": _max_drift(mon),
                "drift_share": mon.get("drift_share"),
                "served_by": d["served_by"],
                "champion": top,
                "decision": d.get("decision"),
            }
        )
    gates = (
        json.loads((run_dir / "gate.json").read_text()) if (run_dir / "gate.json").exists() else {}
    )
    parity = (
        json.loads((run_dir / "parity.json").read_text())
        if (run_dir / "parity.json").exists()
        else {}
    )
    report_dir = SITE / "reports" / run_dir.name
    if (run_dir / "reports").exists():
        shutil.copytree(run_dir / "reports", report_dir, dirs_exist_ok=True)
    evs = []
    for e in events:
        if e["type"] not in KEEP_EVENTS:
            continue
        e = dict(e)
        if e["type"] == "drift_detected" and (report_dir / f"day{e['day']:03d}.html").exists():
            e["report_url"] = f"reports/{run_dir.name}/day{e['day']:03d}.html"
        evs.append(e)
    return {
        "scenario": scenario,
        "label": SCENARIO_LABEL[scenario],
        "source": "fullloop",
        "run": run_dir.name,
        "seed": summary["seed"],
        "drift_start": summary["drift_start"],
        "days": days,
        "events": evs,
        "gates": gates,
        "parity": parity,
        "summary": summary,
    }


def _from_backtest(set_name: str, scenario: str, seed: int) -> dict:
    path = BACKTEST / set_name / scenario / "drift" / f"seed{seed}.json"
    r = json.loads(path.read_text())
    roll = rolling(r["days"], 7)
    days = [
        {
            "day": d["day"],
            "recall": roll.get(d["day"]),
            "recall_day": d["recall"],
            "delayed_pr_auc": d["monitor"].get("delayed_pr_auc"),
            "delayed_recall": d["monitor"].get("delayed_recall"),
            "drift": _max_drift(d["monitor"]),
            "drift_share": d["monitor"].get("drift_share"),
            "champion": str(d["champion_version"]),
            "decision": d["decision"],
        }
        for d in r["days"]
    ]
    return {
        "scenario": scenario,
        "label": SCENARIO_LABEL[scenario],
        "source": "backtest",
        "run": f"{set_name}/{scenario}/drift/seed{seed}",
        "seed": seed,
        "drift_start": r["drift_start"],
        "days": days,
        "events": [e for e in r["events"] if e["type"] in KEEP_EVENTS],
    }


def build(set_name: str = "test") -> list[Path]:
    data_dir = SITE / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed = json.loads((REPO_ROOT / "results" / f"summary_{set_name}.json").read_text())["config"][
        "seeds"
    ][set_name][0]
    index, written = [], []
    for scenario in SCENARIO_LABEL:
        run_dir = _latest_fullloop(set_name, scenario)
        data = (
            _from_fullloop(run_dir, scenario)
            if run_dir
            else _from_backtest(set_name, scenario, seed)
        )
        out = data_dir / f"timeline-{scenario}.json"
        out.write_text(json.dumps(data, default=float))
        written.append(out)
        index.append(
            {
                "scenario": scenario,
                "label": data["label"],
                "source": data["source"],
                "run": data["run"],
                "file": f"data/{out.name}",
            }
        )
    summary = json.loads((REPO_ROOT / "results" / f"summary_{set_name}.json").read_text())
    slim = {
        k: {kk: vv for kk, vv in v.items() if kk != "per_seed"} for k, v in summary["table"].items()
    }
    (data_dir / "summary.json").write_text(
        json.dumps({"set": set_name, "table": slim, "config": summary["config"]}, default=float)
    )
    (data_dir / "scenarios.json").write_text(json.dumps(index, indent=1))
    return written
