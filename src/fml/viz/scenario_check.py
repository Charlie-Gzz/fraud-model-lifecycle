"""A quick look at each scenario: does the drift start when and how it should?"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from fml import REPO_ROOT
from fml.data import generator, scenarios
from fml.features.definitions import CATEGORY_CODE
from fml.viz import theme


def plot(set_name: str = "dev", seed: int = 101, out_dir: Path | None = None) -> list[Path]:
    theme.apply()
    scs = {s.name: s for s in scenarios.load_set(set_name)}
    panels = [
        (
            "amount_drift",
            "Median legit amount ($)",
            lambda d: d[d.is_fraud == 0].groupby("day").amount.median(),
        ),
        (
            "new_category",
            "Crypto share of transactions (%)",
            lambda d: 100 * (d.category == CATEGORY_CODE["crypto_exchange"]).groupby(d.day).mean(),
        ),
        (
            "new_fraud_pattern",
            "Scam transactions per day",
            lambda d: (d.pattern == "scam").groupby(d.day).sum(),
        ),
        ("control", "Fraud transactions per day", lambda d: d.is_fraud.groupby(d.day).sum()),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True)
    for ax, (name, ylabel, fn) in zip(axes.flat, panels, strict=True):
        sc = scs[name]
        series = fn(generator.generate(sc, seed))
        ax.plot(series.index, series.values, color=theme.ACCENT, lw=1.6)
        if sc.drift_start is not None:
            ax.axvline(sc.drift_start, color=theme.WARN, ls="--", lw=1.2)
            ax.text(
                sc.drift_start - 1.5,
                ax.get_ylim()[1] * 0.95,
                f"drift starts day {sc.drift_start}",
                color=theme.WARN,
                va="top",
                ha="right",
                fontsize=10,
            )
        ax.set_title(name.replace("_", " "))
        ax.set_ylabel(ylabel)
    for ax in axes[1]:
        ax.set_xlabel("simulated day")
    theme.suptitle(
        fig,
        f"Each drift switches on exactly where the scenario says ({set_name} set, seed {seed})",
        "Control stays flat apart from weekly seasonality and noise",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return theme.save(fig, out_dir or REPO_ROOT / "assets" / "charts", f"scenario_check_{set_name}")


if __name__ == "__main__":
    for s in ("dev", "test"):
        print(plot(s, seed=101 if s == "dev" else 201))
