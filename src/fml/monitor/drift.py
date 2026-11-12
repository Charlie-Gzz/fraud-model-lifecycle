"""Data drift and prediction drift with Evidently.

Reference = a sample of the champion's training features (and its scores on them).
Current   = the last week of served traffic (features as computed online, and scores).
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pandas as pd

from fml.features.definitions import FEATURES

warnings.filterwarnings("ignore", module="evidently")

CATEGORICAL_DRIFT = ["category_code", "is_new_device", "new_merchant_7d"]
NUMERICAL_DRIFT = [f for f in FEATURES if f not in CATEGORICAL_DRIFT]
REFERENCE_SAMPLE = 20_000
CURRENT_SAMPLE = 20_000

# Evidently's own default thresholds for these distance methods. Fixed before any
# policy comparison; see docs/DECISIONS.md.
NUM_METHOD, NUM_THRESHOLD = "wasserstein", 0.1
CAT_METHOD, CAT_THRESHOLD = "jensenshannon", 0.1

_COL = re.compile(r"ValueDrift\(column=([^,]+),method=([^,]+),threshold=([0-9.]+)\)")


def _sample(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.sample(n, random_state=0) if len(df) > n else df


def drift_report(
    reference: pd.DataFrame, current: pd.DataFrame, html_path: Path | str | None = None
) -> dict:
    """Per-column drift scores, the share of drifted features, and prediction drift.

    Both frames need the FEATURES columns and a `score` column."""
    from evidently import DataDefinition, Dataset, Report
    from evidently.presets import DataDriftPreset

    cols = FEATURES + ["score"]
    ref = _sample(reference[cols], REFERENCE_SAMPLE)
    cur = _sample(current[cols], CURRENT_SAMPLE)
    definition = DataDefinition(
        numerical_columns=NUMERICAL_DRIFT + ["score"], categorical_columns=CATEGORICAL_DRIFT
    )
    preset = DataDriftPreset(
        num_method=NUM_METHOD,
        num_threshold=NUM_THRESHOLD,
        cat_method=CAT_METHOD,
        cat_threshold=CAT_THRESHOLD,
    )
    snap = Report([preset]).run(
        current_data=Dataset.from_pandas(cur, data_definition=definition),
        reference_data=Dataset.from_pandas(ref, data_definition=definition),
    )
    if html_path is not None:
        snap.save_html(str(html_path))

    scores, drifted = {}, []
    for m in snap.dict()["metrics"]:
        match = _COL.match(m.get("metric_name", ""))
        if not match:
            continue
        col, threshold = match.group(1), float(match.group(3))
        value = float(m["value"])
        scores[col] = value
        if col != "score" and value >= threshold:
            drifted.append(col)
    feature_scores = {c: scores[c] for c in FEATURES if c in scores}
    return {
        "drift_share": len(drifted) / len(FEATURES),
        "drifted_features": drifted,
        "feature_scores": feature_scores,
        "prediction_drift": scores.get("score", float("nan")),
        "n_reference": len(ref),
        "n_current": len(cur),
    }
