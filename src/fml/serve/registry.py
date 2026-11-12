"""MLflow registry access shared by the trainer, the service and the pipeline."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

MODEL_NAME = os.environ.get("MODEL_NAME", "fraud-detector")
CHAMPION, CHALLENGER = "champion", "challenger"


def client():
    from mlflow import MlflowClient

    return MlflowClient()


@dataclass
class LoadedModel:
    version: str
    booster: object
    threshold: float
    features: list[str]


def resolve_version(ref: str | None) -> str | None:
    """`ref` is a version number, an alias, or empty (= champion). None if nothing exists."""
    from mlflow.exceptions import MlflowException

    c = client()
    ref = ref or CHAMPION
    if ref == "none":  # explicit warm-up mode
        return None
    if ref.isdigit():
        return ref
    try:
        return c.get_model_version_by_alias(MODEL_NAME, ref).version
    except MlflowException:
        return None


def load(version: str) -> LoadedModel:
    import lightgbm as lgb
    import mlflow

    with tempfile.TemporaryDirectory() as tmp:
        path = mlflow.artifacts.download_artifacts(
            artifact_uri=f"models:/{MODEL_NAME}/{version}", dst_path=tmp
        )
        meta = json.loads((Path(path) / "meta.json").read_text())
        booster = lgb.Booster(model_file=str(Path(path) / "model.txt"))
    return LoadedModel(version, booster, float(meta["threshold"]), list(meta["features"]))


def set_alias(alias: str, version: str) -> None:
    client().set_registered_model_alias(MODEL_NAME, alias, version)


def version_tags(version: str) -> dict:
    return dict(client().get_model_version(MODEL_NAME, version).tags)
