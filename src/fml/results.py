"""Turn saved backtest runs into the numbers the README reports. No cluster needed.

Definitions (fixed in configs/experiment.yaml before the test set was run):
- fraud caught      = recall at the 1% daily alert budget, pooled over days
- dollars caught    = share of fraud dollars inside the daily alert budget
- baseline          = pooled recall of the no-retraining policy over the 14 days before drift
- post-drift        = pooled over every day from the drift start to the end of the run
- recovered share   = (policy post-drift - no-retrain post-drift) / (baseline - no-retrain
                      post-drift): how much of the lost catch a policy wins back
- time to recover   = days from drift start until the 7-day rolling recall is back to 95% of
                      baseline after first falling below it (None if it never comes back)
- time to detect    = days from drift start to the first drift alarm (drift policy only)
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from fml import REPO_ROOT
from fml.backtest.runner import RESULTS as BACKTEST
from fml.policy import load_config

SET_DRIFT_START = {"dev": 55, "test": 65}  # control runs are scored over the same window


def pooled(days: list[dict], lo: int, hi: int, key: str = "recall") -> float:
    sel = [d for d in days if lo <= d["day"] <= hi and d["n_fraud"] > 0]
    if key == "recall":
        n = sum(d["n_fraud"] for d in sel)
        return sum(d["recall"] * d["n_fraud"] for d in sel) / n if n else float("nan")
    total = sum(d["fraud_dollars"] for d in sel)
    return sum(d["caught_dollars"] for d in sel) / total if total else float("nan")


def rolling(days: list[dict], window: int) -> dict[int, float]:
    by_day = {d["day"]: d for d in days}
    out = {}
    for day in by_day:
        sel = [by_day[x] for x in range(day - window + 1, day + 1) if x in by_day]
        if len(sel) == window:
            n = sum(d["n_fraud"] for d in sel)
            out[day] = sum(d["recall"] * d["n_fraud"] for d in sel) / n if n else float("nan")
    return out


def time_to_recover(days: list[dict], start: int, baseline: float, rec: dict) -> int | None:
    """Days from `start` until rolling recall is back above target and stays there for
    `sustain_days`, after first dropping below it. 0 if it never dropped, None if it never
    came back."""
    target = rec["recovered_at"] * baseline
    sustain = rec.get("sustain_days", 1)
    roll = rolling(days, rec["rolling_days"])
    after = sorted((d, r) for d, r in roll.items() if d >= start)
    if not any(r < target for _, r in after):
        return 0
    first_drop = next(d for d, r in after if r < target)
    later = [(d, r) for d, r in after if d > first_drop]
    for i, (d, _) in enumerate(later):
        window = later[i : i + sustain]
        if len(window) == sustain and all(r >= target for _, r in window):
            return d - start
    return None


def summarize(run: dict, none_run: dict, cfg: dict) -> dict:
    days, start, end = run["days"], SET_DRIFT_START[run["set"]], run["n_days"] - 1
    base_days = cfg["recovery"]["baseline_days"]
    baseline = pooled(none_run["days"], start - base_days, start - 1)
    none_post = pooled(none_run["days"], start, end)
    post = pooled(days, start, end)
    lost = baseline - none_post
    alarms = [e["day"] for e in run["events"] if e["type"] == "drift_detected"]
    retrain_days = [e["day"] for e in run["events"] if e["type"] == "retrain_started"]
    return {
        "scenario": run["scenario_name"],
        "policy": run["policy"],
        "seed": run["seed"],
        "recall_all": pooled(days, 28, end),
        "dollars_all": pooled(days, 28, end, "dollars"),
        "baseline_recall": baseline,
        "recall_post": post,
        "dollars_post": pooled(days, start, end, "dollars"),
        "lost_catch": lost,
        "recovered_share": (post - none_post) / lost if lost > 0.02 else float("nan"),
        "time_to_recover": time_to_recover(days, start, baseline, cfg["recovery"]),
        "time_to_detect": next((d - start for d in alarms if d >= start), None),
        "false_alarms_before_drift": sum(1 for d in alarms if d < start),
        "retrains": run["retrains"],
        "retrains_before_drift": sum(1 for d in retrain_days if d < start),
        "promotions": run["promotions"],
    }


def load_runs(set_name: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((BACKTEST / set_name).glob("*/*/seed*.json"))]


def aggregate(rows: list[dict]) -> dict:
    """Mean, min and max across seeds for every numeric field (None/NaN ignored)."""
    out = {}
    for key in rows[0]:
        if key in ("scenario", "policy", "seed"):
            continue
        vals = [
            r[key]
            for r in rows
            if r[key] is not None and not (isinstance(r[key], float) and np.isnan(r[key]))
        ]
        missing = len(rows) - len(vals)
        out[key] = {
            "mean": float(np.mean(vals)) if vals else None,
            "min": float(np.min(vals)) if vals else None,
            "max": float(np.max(vals)) if vals else None,
            "n": len(vals),
            "missing": missing,
        }
    return out


def build(set_name: str = "test") -> dict:
    cfg = load_config()
    runs = load_runs(set_name)
    by_key = {(r["scenario_name"], r["policy"], r["seed"]): r for r in runs}
    rows = defaultdict(list)
    for (scenario, policy, seed), run in sorted(by_key.items()):
        none_run = by_key.get((scenario, "none", seed))
        if none_run is None:
            continue
        rows[(scenario, policy)].append(summarize(run, none_run, cfg))
    table = {
        f"{s}/{p}": {"seeds": [r["seed"] for r in rs], "per_seed": rs, **aggregate(rs)}
        for (s, p), rs in rows.items()
    }
    sanity(table)
    return {"set": set_name, "config": cfg, "table": table}


def sanity(table: dict) -> None:
    """Refuse impossible numbers before anything gets charted."""
    for key, row in table.items():
        for r in row["per_seed"]:
            for field in ("recall_all", "recall_post", "dollars_all", "dollars_post"):
                v = r[field]
                if not (np.isnan(v) or 0.0 <= v <= 1.0):
                    raise ValueError(f"{key} seed {r['seed']}: {field}={v} is impossible")
            if r["policy"] == "none" and r["retrains"] != 0:
                raise ValueError(f"{key}: the no-retrain policy retrained")


def fmt(stat: dict, pct: bool = True, digits: int = 1) -> str:
    if stat["mean"] is None:
        return "n/a"
    f = (lambda v: f"{100 * v:.{digits}f}%") if pct else (lambda v: f"{v:.{digits}f}")
    s = f"{f(stat['mean'])} ({f(stat['min'])} to {f(stat['max'])})"
    if stat.get("missing"):
        s += f", {stat['missing']} never"
    return s


def markdown(summary: dict) -> str:
    lines = [
        f"# Policy comparison ({summary['set']} scenarios)",
        "",
        "Mean across seeds, with min to max in brackets. Generated by `fml results`.",
        "",
        "| Scenario | Policy | Fraud caught after drift | Dollars caught after drift | "
        "Recovered share of lost catch | Days to recover | Days to detect | Retrains |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key, row in summary["table"].items():
        scenario, policy = key.split("/")
        lines.append(
            f"| {scenario} | {policy} | {fmt(row['recall_post'])} | {fmt(row['dollars_post'])} | "
            f"{fmt(row['recovered_share'], digits=0)} | {fmt(row['time_to_recover'], False, 1)} | "
            f"{fmt(row['time_to_detect'], False, 1)} | {fmt(row['retrains'], False, 1)} |"
        )
    return "\n".join(lines) + "\n"


def write(set_name: str = "test", out_dir: Path | None = None) -> Path:
    summary = build(set_name)
    out_dir = out_dir or REPO_ROOT / "results"
    path = out_dir / f"summary_{set_name}.json"
    path.write_text(json.dumps(summary, indent=1, default=float))
    (out_dir / f"summary_{set_name}.md").write_text(markdown(summary))
    return path
