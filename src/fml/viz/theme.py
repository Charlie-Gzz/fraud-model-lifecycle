"""One look for every chart: the Tideline dark palette (PLAN.md Section 6)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

BG = "#0B0F17"
PANEL = "#131A26"
BORDER = "#1F2937"
TEXT = "#E5E7EB"
MUTED = "#9CA3AF"
ACCENT = "#2DD4BF"
HEALTHY = "#22C55E"
WARN = "#F59E0B"
ALERT = "#EF4444"
CHAMPION = "#2DD4BF"
CHALLENGER = "#A78BFA"

# Policies: colour plus line style, so colour is never the only signal. These three
# pass the dataviz palette validator on the dark panel (lightness band, chroma, CVD and
# normal-vision separation, contrast). The lighter accent teal fails the lightness band
# for chart series, so it stays a UI colour.
POLICY_STYLE = {
    "none": {"color": "#EC4899", "linestyle": ":", "label": "No retraining"},
    "scheduled": {"color": "#8B5CF6", "linestyle": "--", "label": "Weekly retraining"},
    "drift": {"color": "#0D9488", "linestyle": "-", "label": "Drift-triggered retraining"},
}
POLICY_ORDER = ["drift", "scheduled", "none"]


def _font(preferred: str, fallback: str = "DejaVu Sans") -> str:
    names = {f.name for f in font_manager.fontManager.ttflist}
    return preferred if preferred in names else fallback


def apply() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": BG,
            "axes.facecolor": PANEL,
            "savefig.facecolor": BG,
            "axes.edgecolor": BORDER,
            "axes.labelcolor": MUTED,
            "axes.titlecolor": TEXT,
            "axes.titleweight": "semibold",
            "axes.titlesize": 13,
            "axes.titlelocation": "left",
            "axes.grid": True,
            "grid.color": BORDER,
            "grid.linewidth": 0.8,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "text.color": TEXT,
            "legend.frameon": False,
            "legend.labelcolor": TEXT,
            "font.family": _font("Inter"),
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def save(fig, out_dir: Path, name: str, width_px: int = 1600) -> list[Path]:
    """PNG at `width_px` wide plus SVG."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dpi = width_px / fig.get_size_inches()[0]
    paths = [out_dir / f"{name}.png", out_dir / f"{name}.svg"]
    fig.savefig(paths[0], dpi=dpi, bbox_inches="tight", pad_inches=0.25)
    fig.savefig(paths[1], bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return paths


def suptitle(fig, title: str, subtitle: str | None = None) -> None:
    fig.text(0.01, 0.995, title, ha="left", va="top", fontsize=16, weight="bold", color=TEXT)
    if subtitle:
        fig.text(0.01, 0.955, subtitle, ha="left", va="top", fontsize=11, color=MUTED)
