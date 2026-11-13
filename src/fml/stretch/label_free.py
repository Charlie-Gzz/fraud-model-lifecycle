"""Stretch 2: a label-free performance estimate, shown before delayed labels arrive.

If the model's scores are calibrated probabilities, the expected number of frauds in a
day is the sum of the scores, and the expected number caught inside the 1% budget is
the sum of the flagged scores. Their ratio estimates recall at the budget with no labels
at all (the idea behind confidence-based performance estimation, CBPE).

It can only see what the model sees: if a new kind of fraud looks normal to the model,
the estimate stays high while true recall falls. This script measures exactly that, for
the bootstrap model with no retraining, on the test scenarios.

    uv run python -m fml.stretch.label_free
"""

from __future__ import annotations

import json

import matplotlib.pyplot as plt
import numpy as np

from fml import REPO_ROOT, lifecycle
from fml.backtest import engine
from fml.data import generator, scenarios
from fml.train import model as M
from fml.viz import charts, theme

OUT = REPO_ROOT / "results" / "stretch"
SEEDS = [201, 202, 203, 204, 205]
START = 65


def daily_series(sc, seed: int) -> dict:
    P = engine.prepare(sc, seed)
    boot = engine.train_challenger(P, lifecycle.FIRST_TRAIN_DAY, seed, version=1)
    days = list(range(lifecycle.FIRST_TRAIN_DAY + 1, sc.n_days))
    true_r, est_r, settled_r = [], [], []
    scores = np.full(len(P.day), np.nan)
    for d in days:
        today = P.day == d
        s = M.score(boot.booster, P.F[today])
        scores[today] = s
        flagged = M.alerts_at_budget(s, P.day[today])
        y = P.y[today]
        true_r.append(float(flagged[y == 1].mean()) if y.sum() else np.nan)
        est_r.append(float(s[flagged].sum() / s.sum()))
        # What the monitor knows that day: recall on settled labels only.
        lo, hi = lifecycle.performance_window(d)
        perf = (P.day >= max(lo, days[0])) & (P.day <= hi)
        if perf.any():
            known = generator.known_labels(P.df, d).to_numpy()[perf]
            m = M.evaluate(scores[perf], known, P.day[perf], P.amount[perf])
            settled_r.append(m["recall_at_budget"])
        else:
            settled_r.append(np.nan)
    return {"days": days, "true": true_r, "estimate": est_r, "settled": settled_r}


def rolling(x: list[float], w: int = 7) -> np.ndarray:
    a = np.array(x, dtype=float)
    out = np.full(len(a), np.nan)
    for i in range(w - 1, len(a)):
        out[i] = np.nanmean(a[i - w + 1 : i + 1])
    return out


def first_drop_day(days, series, baseline, drop=0.05) -> int | None:
    """First day after START when the 7-day mean is `drop` below its pre-drift level."""
    for d, v in zip(days, series, strict=True):
        if d >= START and not np.isnan(v) and v < baseline - drop:
            return d - START
    return None


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    result = {}
    for sc in scenarios.load_set("test"):
        per_seed = [daily_series(sc, s) for s in SEEDS]
        days = per_seed[0]["days"]
        series = {
            k: np.nanmean([rolling(p[k]) for p in per_seed], axis=0)
            for k in ("true", "estimate", "settled")
        }
        pre = [i for i, d in enumerate(days) if START - 14 <= d < START]
        base = {k: float(np.nanmean(series[k][pre])) for k in series}
        result[sc.name] = {
            "days": days,
            **{k: [None if np.isnan(v) else float(v) for v in series[k]] for k in series},
            "days_to_drop": {k: first_drop_day(days, series[k], base[k]) for k in series},
            "baseline": base,
        }
    (OUT / "label_free_estimate.json").write_text(json.dumps(result, indent=1))
    plot(result)
    return result


def plot(result: dict) -> None:
    theme.apply()
    fig, axes = plt.subplots(2, 2, figsize=(15, 9), sharex=True, sharey=True)
    styles = {
        "true": ("True recall (needs labels from the future)", theme.TEXT, "-"),
        "estimate": ("Label-free estimate (scores only, same day)", theme.ACCENT, "--"),
        "settled": ("Recall on settled labels (what the monitor sees)", theme.CHALLENGER, ":"),
    }
    for ax, name in zip(axes.flat, charts.SCENARIOS, strict=True):
        r = result[name]
        for key, (label, color, ls) in styles.items():
            ax.plot(
                r["days"],
                [np.nan if v is None else 100 * v for v in r[key]],
                color=color,
                ls=ls,
                lw=2,
                label=label,
            )
        if name != "control":
            ax.axvline(START, color=theme.WARN, ls="--", lw=1.2)
        ax.set_title(charts.SCENARIO_LABEL[name])
        ax.set_ylim(30, 100)
    for ax in axes[:, 0]:
        ax.set_ylabel("recall at 1% budget (%), 7-day mean")
    for ax in axes[1]:
        ax.set_xlabel("simulated day (no retraining)")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.01))
    drifts = [n for n in charts.SCENARIOS if n != "control"]
    est = [result[n]["days_to_drop"]["estimate"] for n in drifts]
    settled = [
        result[n]["days_to_drop"]["settled"]
        for n in drifts
        if result[n]["days_to_drop"]["settled"] is not None
    ]
    gap = np.mean(
        [
            result[n]["baseline"]["estimate"] - result[n]["baseline"]["true"]
            for n in charts.SCENARIOS
        ]
    )
    if all(e is None for e in est):
        title = (
            f"The label-free estimate never noticed any of the drifts; settled labels did, "
            f"{min(settled)} to {max(settled)} days after the drift started"
        )
    else:
        title = "The label-free estimate reacts to some drifts, but not to a new fraud pattern"
    theme.suptitle(
        fig,
        title,
        f"Test scenarios, bootstrap model never retrained, mean of 5 seeds; the estimate also "
        f"runs {100 * gap:.0f} points too high. Amber line = drift starts.",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.92))
    theme.save(fig, REPO_ROOT / "assets" / "charts", "label_free_estimate")


if __name__ == "__main__":
    res = run()
    for k, v in res.items():
        print(
            k,
            "days to a 5-point drop:",
            v["days_to_drop"],
            "baseline:",
            {kk: round(vv, 3) for kk, vv in v["baseline"].items()},
        )
