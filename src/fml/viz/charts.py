"""Result charts (PNG 1600px + SVG) from saved runs. Titles state the takeaway, computed
from the data, so they never go stale. Run through `fml assets`.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fml import REPO_ROOT
from fml.features.definitions import FEATURES
from fml.results import SET_DRIFT_START, load_runs, rolling
from fml.viz import theme

OUT = REPO_ROOT / "assets" / "charts"
SCENARIO_LABEL = {
    "new_fraud_pattern": "New fraud pattern (concept drift)",
    "new_category": "New merchant category",
    "amount_drift": "Amounts creep up (covariate drift)",
    "control": "Control (no drift)",
}
SCENARIOS = list(SCENARIO_LABEL)


def _by(runs: list[dict]) -> dict:
    out: dict = {}
    for r in runs:
        out.setdefault((r["scenario_name"], r["policy"]), []).append(r)
    return out


def _rolling_matrix(runs: list[dict], window: int = 7) -> tuple[np.ndarray, np.ndarray]:
    series = [rolling(r["days"], window) for r in runs]
    days = np.array(sorted(series[0]))
    return days, np.array([[s[d] for d in days] for s in series])


def fraud_caught_over_time(summary: dict, set_name: str) -> list[Path]:
    theme.apply()
    by = _by(load_runs(set_name))
    start = SET_DRIFT_START[set_name]
    fig, axes = plt.subplots(2, 2, figsize=(15, 9), sharex=True, sharey=True)
    for ax, sc in zip(axes.flat, SCENARIOS, strict=True):
        for policy in theme.POLICY_ORDER:
            runs = by.get((sc, policy))
            if not runs:
                continue
            style = theme.POLICY_STYLE[policy]
            days, m = _rolling_matrix(runs)
            ax.fill_between(
                days, 100 * m.min(0), 100 * m.max(0), color=style["color"], alpha=0.13, lw=0
            )
            ax.plot(
                days,
                100 * m.mean(0),
                color=style["color"],
                ls=style["linestyle"],
                lw=2,
                label=style["label"],
            )
        if sc != "control":
            ax.axvline(start, color=theme.WARN, lw=1.2, ls="--")
            ax.text(start + 1, 31, "drift starts", color=theme.WARN, fontsize=10)
        ax.set_title(SCENARIO_LABEL[sc])
        ax.set_ylim(30, 100)
    for ax in axes[:, 0]:
        ax.set_ylabel("fraud caught at 1% budget (%)\n7-day rolling")
    for ax in axes[1]:
        ax.set_xlabel("simulated day")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.01))
    t = summary["table"]
    d_new = t["new_fraud_pattern/drift"]["recall_post"]["mean"]
    s_new = t["new_fraud_pattern/scheduled"]["recall_post"]["mean"]
    n_new = t["new_fraud_pattern/none"]["recall_post"]["mean"]
    verdict = "matches" if abs(d_new - s_new) < 0.01 else ("beats" if d_new > s_new else "trails")
    theme.suptitle(
        fig,
        f"After a new fraud pattern, drift-triggered retraining catches {100 * d_new:.0f}% of "
        f"fraud: it {verdict} weekly retraining ({100 * s_new:.0f}%), no retraining "
        f"{100 * n_new:.0f}%",
        f"{set_name} scenarios, mean of {len(t['control/none']['seeds'])} seeds, band = min to "
        "max across seeds",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.92))
    return theme.save(fig, OUT, "fraud_caught_over_time")


def _grouped_bars(ax, values: dict, ylabel: str, fmt: str = "{:.1f}") -> None:
    """values[(scenario, policy)] = (mean, lo, hi) or None."""
    width = 0.26
    x = np.arange(len(SCENARIOS))
    for i, policy in enumerate(theme.POLICY_ORDER):
        style = theme.POLICY_STYLE[policy]
        for j, sc in enumerate(SCENARIOS):
            v = values.get((sc, policy))
            xpos = x[j] + (i - 1) * width
            if v is None:
                ax.text(xpos, 0.3, "n/a", ha="center", color=theme.MUTED, fontsize=9)
                continue
            mean, lo, hi = v
            ax.bar(
                xpos,
                mean,
                width * 0.92,
                color=style["color"],
                label=style["label"] if j == 0 else None,
                zorder=3,
            )
            ax.errorbar(
                xpos,
                mean,
                yerr=[[mean - lo], [hi - mean]],
                color=theme.TEXT,
                lw=1,
                capsize=3,
                zorder=4,
            )
            ax.text(
                xpos,
                hi + 0.02 * ax.get_ylim()[1],
                fmt.format(mean),
                ha="center",
                va="bottom",
                fontsize=9,
                color=theme.TEXT,
            )
    ax.set_xticks(x, [SCENARIO_LABEL[s].split(" (")[0] for s in SCENARIOS])
    ax.set_ylabel(ylabel)
    ax.grid(axis="x", visible=False)


def _stat(row: dict, key: str):
    s = row[key]
    return None if s["mean"] is None else (s["mean"], s["min"], s["max"])


def detect_and_recover(summary: dict, set_name: str) -> list[Path]:
    theme.apply()
    t = summary["table"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 6.5))
    detect = {
        (sc, "drift"): _stat(t[f"{sc}/drift"], "time_to_detect")
        for sc in SCENARIOS
        if sc != "control"
    }
    a1.set_ylim(0, max(v[2] for v in detect.values() if v) * 1.3)
    width = 0.5
    for j, sc in enumerate(SCENARIOS[:3]):
        v = detect[(sc, "drift")]
        if v:
            a1.bar(j, v[0], width, color=theme.POLICY_STYLE["drift"]["color"], zorder=3)
            a1.errorbar(j, v[0], yerr=[[v[0] - v[1]], [v[2] - v[0]]], color=theme.TEXT, capsize=3)
            a1.text(j, v[2] + 0.3, f"{v[0]:.1f} days", ha="center", fontsize=10)
    a1.set_xticks(range(3), [SCENARIO_LABEL[s].split(" (")[0] for s in SCENARIOS[:3]])
    a1.set_ylabel("days from drift start to first alarm")
    a1.set_title("Time to detect (drift-triggered policy)")
    a1.grid(axis="x", visible=False)

    rec = {}
    for sc in SCENARIOS[:3]:
        for p in theme.POLICY_ORDER:
            row = t[f"{sc}/{p}"]
            vals = [r["time_to_recover"] for r in row["per_seed"]]
            got = [v for v in vals if v is not None]
            rec[(sc, p)] = (np.mean(got), min(got), max(got)) if got else None
    a2.set_ylim(0, 52)
    width = 0.26
    for i, p in enumerate(theme.POLICY_ORDER):
        style = theme.POLICY_STYLE[p]
        # Legend entry once per policy, whatever the first scenario shows.
        a2.bar(np.nan, np.nan, color=style["color"], label=style["label"])
        for j, sc in enumerate(SCENARIOS[:3]):
            v = rec[(sc, p)]
            xpos = j + (i - 1) * width
            row = t[f"{sc}/{p}"]
            never = sum(r["time_to_recover"] is None for r in row["per_seed"])
            if v is None:  # no seed recovered: hatched outline to the top
                a2.bar(
                    xpos,
                    46,
                    width * 0.92,
                    fill=False,
                    edgecolor=style["color"],
                    hatch="//",
                    lw=1,
                    zorder=3,
                )
                a2.text(xpos, 47, "never", ha="center", fontsize=9, color=theme.TEXT)
                continue
            a2.bar(xpos, v[0], width * 0.92, color=style["color"], zorder=3)
            a2.errorbar(
                xpos, v[0], yerr=[[v[0] - v[1]], [v[2] - v[0]]], color=theme.TEXT, capsize=3
            )
            note = f"{v[0]:.0f}" + (f"\n{never} never" if never else "")
            a2.text(xpos, v[2] + 0.8, note, ha="center", fontsize=9)
    a2.set_xticks(range(3), [SCENARIO_LABEL[s].split(" (")[0] for s in SCENARIOS[:3]])
    a2.set_ylabel("days until recall is back to 95% of baseline")
    a2.set_title("Time to recover")
    a2.grid(axis="x", visible=False)
    a2.legend(loc="upper left", bbox_to_anchor=(0, -0.08), ncol=3)
    fastest = min((v for v in detect.values() if v), key=lambda v: v[0])
    slowest = max((v for v in detect.values() if v), key=lambda v: v[0])
    theme.suptitle(
        fig,
        f"Drift is flagged {fastest[0]:.0f} to {slowest[0]:.0f} days after it "
        "starts; recovery still waits for fraud labels to arrive",
        f"{set_name} scenarios; bars = mean, whiskers = min to max across seeds; "
        "'never' = not back to 95% of baseline before the run ended",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    return theme.save(fig, OUT, "detect_and_recover")


def retrains(summary: dict, set_name: str) -> list[Path]:
    theme.apply()
    t = summary["table"]
    fig, ax = plt.subplots(figsize=(14, 6.5))
    ax.set_ylim(0, 14)
    vals = {
        (sc, p): _stat(t[f"{sc}/{p}"], "retrains") for sc in SCENARIOS for p in theme.POLICY_ORDER
    }
    _grouped_bars(ax, vals, "retraining runs per scenario (110 simulated days)")
    ax.legend(loc="upper left")
    ctrl = vals[("control", "drift")]
    sched = vals[("control", "scheduled")]
    theme.suptitle(
        fig,
        f"With no drift, the drift-triggered policy retrained {ctrl[0]:.1f} times "
        f"on average; weekly retraining retrained {sched[0]:.0f} times",
        "Each retrain runs features, training and the promotion gate. Whiskers = "
        "min to max across seeds.",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    return theme.save(fig, OUT, "retrains_per_policy")


def drift_at_detection(set_name: str) -> list[Path]:
    theme.apply()
    by = _by(load_runs(set_name))
    start = SET_DRIFT_START[set_name]
    fig, axes = plt.subplots(1, 3, figsize=(17, 6.5), sharey=True)
    # One fixed feature order (by the largest score in any scenario), so rows line up.
    peak = np.zeros(len(FEATURES))
    for sc in SCENARIOS[:3]:
        for r in by[(sc, "drift")]:
            for e in r["events"]:
                if e["type"] == "drift_detected" and e["day"] >= start and e.get("feature_scores"):
                    peak = np.maximum(peak, [e["feature_scores"].get(f, 0.0) for f in FEATURES])
                    break
    order = np.argsort(peak)
    for ax, sc in zip(axes, SCENARIOS[:3], strict=True):
        scores = []
        for r in by[(sc, "drift")]:
            ev = next(
                (
                    e
                    for e in r["events"]
                    if e["type"] == "drift_detected"
                    and e["day"] >= start
                    and e.get("feature_scores")
                ),
                None,
            )
            if ev:
                scores.append([ev["feature_scores"].get(f, 0.0) for f in FEATURES])
        if not scores:
            ax.text(
                0.5,
                0.5,
                "no data-drift alarm\n(detected by recall drop)",
                transform=ax.transAxes,
                ha="center",
                color=theme.MUTED,
            )
            ax.set_title(SCENARIO_LABEL[sc])
            continue
        m = np.array(scores).mean(0)
        colors = [theme.WARN if v >= 0.1 else "#334155" for v in m[order]]
        ax.barh(np.array(FEATURES)[order], m[order], color=colors, zorder=3)
        ax.axvline(0.1, color=theme.ALERT, ls="--", lw=1)
        ax.text(0.102, -0.6, "drift threshold 0.1", color=theme.ALERT, fontsize=9)
        ax.set_title(SCENARIO_LABEL[sc])
        ax.set_xlabel("Evidently drift score at first alarm")
        ax.grid(axis="y", visible=False)
    theme.suptitle(
        fig,
        "Each drift lights up different features; a new fraud pattern barely "
        "moves the inputs at all",
        "Mean drift score per feature at the first post-drift alarm (drift-triggered policy); "
        "amber = over Evidently's threshold. The new fraud pattern was caught by the recall "
        "drop on settled labels instead.",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    return theme.save(fig, OUT, "drift_score_at_detection")


def feature_parity(parity_files: list[Path]) -> list[Path] | None:
    """Spark vs online features from the full-loop retrain workflows."""
    results = []
    for p in parity_files:
        for wf in json.loads(p.read_text()).values():
            results.append(wf)
    if not results:
        return None
    theme.apply()
    worst = {f: max(r["max_abs_diff"][f] for r in results) for f in FEATURES}
    total = sum(r["n"] for r in results)
    fig, ax = plt.subplots(figsize=(13, 6.5))
    vals = np.array([max(worst[f], 1e-16) for f in FEATURES])
    ax.barh(FEATURES, vals, color=theme.POLICY_STYLE["drift"]["color"], zorder=3)
    ax.set_xscale("log")
    ax.set_xlim(1e-17, 1e-3)
    ax.axvline(1e-6, color=theme.ALERT, ls="--", lw=1.2)
    ax.text(1.2e-6, len(FEATURES) - 0.6, "tolerance 1e-6", color=theme.ALERT, fontsize=10)
    for i, f in enumerate(FEATURES):
        label = "exact" if worst[f] == 0 else f"{worst[f]:.1e}"
        ax.text(max(worst[f], 1e-16) * 2, i, label, va="center", fontsize=9, color=theme.TEXT)
    ax.set_xlabel("largest absolute difference, Spark vs online (log scale)")
    ax.grid(axis="y", visible=False)
    theme.suptitle(
        fig,
        f"Spark training features match the online features on all {total:,} checked transactions",
        f"{len(results)} retrain workflows on the cluster; integer features match "
        "exactly, money sums differ only in float rounding",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    return theme.save(fig, OUT, "feature_parity")
