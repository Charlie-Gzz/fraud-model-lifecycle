"""Retraining pipeline steps. Each one is a container step in the Argo Workflow
(k8s/workflow-retrain.yaml) and passes data to the next through S3:

  gather -> features (Spark) -> parity -> train -> gate -> rollout

Usage: python -m fml.pipeline.steps <step> --run RUN --day DAY --wf WORKFLOW [--seed N]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from fml import events, lifecycle, storage
from fml.features.definitions import FEATURES, PARITY_TOLERANCE

TXN_COLS = ["txn_id", "ts", "user_id", "merchant_id", "category", "device_id", "amount", "day"]


def _p(args, name: str) -> str:
    return f"runs/{args.run}/pipeline/{args.wf}/{name}"


def read_predictions(run: str, max_day: int, min_day: int = 0) -> pd.DataFrame:
    from concurrent.futures import ThreadPoolExecutor

    keys = [k for k in storage.list_keys(f"runs/{run}/predictions/") if k.endswith(".parquet")]
    keys = [k for k in keys if min_day <= int(k.split("day=")[1][:3]) <= max_day]
    with ThreadPoolExecutor(16) as pool:
        frames = list(pool.map(storage.get_df, keys))
    df = pd.concat(frames, ignore_index=True)
    # A retried request can be logged twice; the features are identical, keep one.
    return df.drop_duplicates("txn_id", keep="last").sort_values("txn_id", ignore_index=True)


def read_labels(run: str, as_of_day: int) -> pd.DataFrame:
    keys = [k for k in storage.list_keys(f"runs/{run}/labels/") if k.endswith(".parquet")]
    keys = [k for k in keys if int(k.split("day=")[1][:3]) <= as_of_day]
    frames = [storage.get_df(k) for k in keys]
    if not frames:
        return pd.DataFrame({"txn_id": [], "report_day": []})
    return pd.concat(frames, ignore_index=True)


def gather(args) -> None:
    pred = read_predictions(args.run, args.day)
    raw = pred[TXN_COLS].copy()
    raw["category"] = raw["category"].astype(np.int64)
    storage.put_df(_p(args, "raw.parquet"), raw)
    storage.put_df(
        _p(args, "online.parquet"), pred[["txn_id", "day", *FEATURES, "score", "model_version"]]
    )
    storage.put_df(_p(args, "labels.parquet"), read_labels(args.run, args.day))
    print(f"gathered {len(raw)} transactions up to day {args.day}")


def features(args) -> None:
    from fml.features.spark_job import run as spark_run

    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "raw.parquet", Path(tmp) / "features.parquet"
        src.write_bytes(storage.get_bytes(_p(args, "raw.parquet")))
        n = spark_run(str(src), str(dst))
        storage.put_bytes(_p(args, "features.parquet"), dst.read_bytes())
    print(f"spark computed features for {n} transactions")


def parity(args) -> None:
    """Training/serving skew check: Spark features vs the features the service used."""
    spark = storage.get_df(_p(args, "features.parquet")).set_index("txn_id").sort_index()
    online = storage.get_df(_p(args, "online.parquet")).set_index("txn_id").loc[spark.index]
    a, b = spark[FEATURES].to_numpy(float), online[FEATURES].to_numpy(float)
    nan_mismatch = int((np.isnan(a) != np.isnan(b)).sum())
    diff = np.nan_to_num(np.abs(a - b), nan=0.0).max(axis=0)
    result = {
        "n": len(spark),
        "max_abs_diff": dict(zip(FEATURES, diff.round(12).tolist(), strict=True)),
        "nan_mismatches": nan_mismatch,
        "tolerance": PARITY_TOLERANCE,
        "passed": bool(nan_mismatch == 0 and (diff <= PARITY_TOLERANCE).all()),
    }
    storage.put_json(_p(args, "parity.json"), result)
    events.emit(
        args.run,
        args.day,
        "parity_checked",
        "pipeline",
        f"Spark vs online on {len(spark):,} transactions: max diff {diff.max():.2e}",
        workflow=args.wf,
        parity=result,
    )
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit("feature parity failed: training and serving features disagree")


def _training_table(args) -> tuple[pd.DataFrame, np.ndarray]:
    feats = storage.get_df(_p(args, "features.parquet"))
    raw = storage.get_df(_p(args, "raw.parquet"))[["txn_id", "day", "amount"]]
    df = raw.merge(feats.drop(columns=["amount"]), on="txn_id").sort_values("txn_id")
    df["amount"] = raw.set_index("txn_id").loc[df["txn_id"], "amount"].to_numpy()
    labels = storage.get_df(_p(args, "labels.parquet"))
    known = labels.loc[labels["report_day"] <= args.day, "txn_id"]
    y = df["txn_id"].isin(set(known)).to_numpy().astype(np.int8)
    return df.reset_index(drop=True), y


def train(args) -> None:
    import mlflow

    from fml.serve import registry
    from fml.train import model as M  # not imported at top: the Spark image has no LightGBM

    w = lifecycle.windows(args.day)
    df, y = _training_table(args)
    tr = df["day"].between(*w.train).to_numpy()
    ho = df["day"].between(*w.holdout).to_numpy()
    booster = M.train(df[tr], y[tr], seed=args.seed)
    ho_scores = M.score(booster, df[ho])
    metrics = M.evaluate(ho_scores, y[ho], df["day"].to_numpy()[ho], df["amount"].to_numpy()[ho])
    threshold = M.threshold_for_budget(ho_scores)
    ref = df[tr].sample(min(20_000, int(tr.sum())), random_state=args.seed)[FEATURES].copy()
    ref["score"] = M.score(booster, ref)

    mlflow.set_experiment("fraud-lifecycle")
    with tempfile.TemporaryDirectory() as tmp, mlflow.start_run(run_name=args.wf) as run:
        model_dir = Path(tmp) / "model"
        model_dir.mkdir()
        booster.save_model(str(model_dir / "model.txt"))
        meta = {
            "threshold": threshold,
            "features": FEATURES,
            "train_days": w.train,
            "holdout_days": w.holdout,
            "seed": args.seed,
            "sim_run": args.run,
        }
        (model_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        ref.to_parquet(model_dir / "reference.parquet", index=False)
        mlflow.log_params(
            {
                "train_days": f"{w.train[0]}-{w.train[1]}",
                "holdout_days": f"{w.holdout[0]}-{w.holdout[1]}",
                "decision_day": args.day,
                "seed": args.seed,
                "sim_run": args.run,
                "n_train": int(tr.sum()),
                **{k: v for k, v in M.LGB_PARAMS.items() if k not in ("verbose",)},
            }
        )
        mlflow.log_metrics({f"holdout_{k}": v for k, v in metrics.items()})
        mlflow.log_artifacts(str(model_dir), artifact_path="model")
        client = registry.client()
        with contextlib.suppress(Exception):  # fails if it already exists, which is fine
            client.create_registered_model(
                registry.MODEL_NAME,
                description=(
                    "LightGBM fraud model. Aliases: champion (serving), challenger (in canary)."
                ),
            )
        version = client.create_model_version(
            registry.MODEL_NAME,
            source=f"{run.info.artifact_uri}/model",
            run_id=run.info.run_id,
            tags={  # model card
                "data_window": f"days {w.train[0]}-{w.train[1]}",
                "holdout_window": f"days {w.holdout[0]}-{w.holdout[1]}",
                "labels_as_of_day": str(w.labels_as_of),
                "features": ",".join(FEATURES),
                "holdout_recall_at_budget": f"{metrics['recall_at_budget']:.4f}",
                "holdout_pr_auc": f"{metrics['pr_auc']:.4f}",
                "holdout_dollars_caught": f"{metrics['dollars_caught']:.4f}",
                "threshold": f"{threshold:.6f}",
                "seed": str(args.seed),
                "sim_run": args.run,
                "workflow": args.wf,
            },
        ).version
    result = {
        "version": str(version),
        "metrics": metrics,
        "threshold": threshold,
        "train": w.train,
        "holdout": w.holdout,
    }
    storage.put_json(_p(args, "train.json"), result)
    events.emit(
        args.run,
        args.day,
        "challenger_trained",
        "pipeline",
        f"v{version} trained on days {w.train[0]}-{w.train[1]}",
        workflow=args.wf,
        version=str(version),
        metrics=metrics,
    )
    print(json.dumps(result, indent=2))


def gate(args) -> None:
    from fml.serve import registry
    from fml.train import model as M

    trained = storage.get_json(_p(args, "train.json"))
    version = trained["version"]
    champion_version = registry.resolve_version(registry.CHAMPION)
    if champion_version is None:
        passed, reason, champ, chall = True, "no champion yet (bootstrap)", None, trained["metrics"]
    else:
        w = lifecycle.windows(args.day)
        df, y = _training_table(args)
        ho = df["day"].between(*w.holdout).to_numpy()
        ev = (y[ho], df["day"].to_numpy()[ho], df["amount"].to_numpy()[ho])
        champ_model = registry.load(champion_version)
        chall_model = registry.load(version)
        champ = M.evaluate(champ_model.booster.predict(df[ho][FEATURES]), *ev)
        chall = M.evaluate(chall_model.booster.predict(df[ho][FEATURES]), *ev)
        g = M.promotion_gate(champ, chall)
        passed, reason = g.passed, g.reason
    if passed:
        registry.set_alias(registry.CHALLENGER, version)
    decision = {
        "passed": passed,
        "reason": reason,
        "version": version,
        "champion_version": champion_version,
        "champion": champ,
        "challenger": chall,
    }
    storage.put_json(_p(args, "gate.json"), decision)
    events.emit(
        args.run,
        args.day,
        "gate_passed" if passed else "gate_failed",
        "pipeline",
        f"v{version}: {reason}",
        workflow=args.wf,
        version=version,
        champion_version=champion_version,
        champion=champ,
        challenger=chall,
    )
    Path(os.environ.get("ARGO_OUTPUT", "/tmp/passed")).write_text("true" if passed else "false")
    print(json.dumps(decision, indent=2))


def rollout(args) -> None:
    from fml.pipeline.rollout import deploy

    trained = storage.get_json(_p(args, "train.json"))
    deploy(args.run, args.day, trained["version"], args.wf)


STEPS = {
    "gather": gather,
    "features": features,
    "parity": parity,
    "train": train,
    "gate": gate,
    "rollout": rollout,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=STEPS)
    ap.add_argument("--run", required=True)
    ap.add_argument("--day", type=int, required=True)
    ap.add_argument("--wf", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    STEPS[args.step](args)


if __name__ == "__main__":
    main()
