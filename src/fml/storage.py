"""Small S3 helpers for the in-cluster object store (SeaweedFS speaks the S3 API).

Layout inside the bucket, one prefix per full-loop run:
  runs/{run}/predictions/day=NNN/{pod}-{seq}.parquet   request + online features + score
  runs/{run}/labels/day=NNN.parquet                     fraud reported on that day
  runs/{run}/monitor/day=NNN.json                       drift + delayed-label metrics
  runs/{run}/reports/day=NNN.html                       Evidently report
  runs/{run}/pipeline/{workflow}/...                    features, metrics, gate decision
  runs/{run}/events/{time}-{source}-{id}.json           one object per timeline event
Events are separate objects so several writers never race on one file; the timeline
collector merges them into timeline.jsonl.
"""

from __future__ import annotations

import io
import json
import os

import pandas as pd

BUCKET = os.environ.get("FML_BUCKET", "fml")


def client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://seaweedfs:8333"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)


def get_bytes(key: str) -> bytes:
    return client().get_object(Bucket=BUCKET, Key=key)["Body"].read()


def exists(key: str) -> bool:
    try:
        client().head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


def list_keys(prefix: str) -> list[str]:
    keys, token = [], None
    s3 = client()
    while True:
        kw = {"Bucket": BUCKET, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        keys += [o["Key"] for o in resp.get("Contents", [])]
        if not resp.get("IsTruncated"):
            return keys
        token = resp["NextContinuationToken"]


def put_df(key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    put_bytes(key, buf.getvalue())


def get_df(key: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(get_bytes(key)))


def read_prefix(prefix: str) -> pd.DataFrame:
    frames = [get_df(k) for k in list_keys(prefix) if k.endswith(".parquet")]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def put_json(key: str, obj) -> None:
    put_bytes(key, json.dumps(obj, indent=2, default=str).encode(), "application/json")


def get_json(key: str):
    return json.loads(get_bytes(key))
