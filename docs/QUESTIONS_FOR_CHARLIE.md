# Questions for Charlie

Each question has my recommendation and what I did in the meantime. None of these blocked the build.

## 1. SeaweedFS instead of MinIO for object storage?
**Context:** MinIO stopped publishing container images (Docker Hub and Quay both return "not found" for every tag). The plan's fallback was a local PersistentVolume, which would have changed every storage code path.
**Recommendation:** keep SeaweedFS. It is Apache-2.0, speaks the S3 API, and nothing in the code is SeaweedFS-specific (boto3 + an endpoint URL), so swapping back to any S3 store is a one-line change.
**Meanwhile:** built everything on SeaweedFS; README and diagrams say "S3 object store (SeaweedFS)".

## 2. Keep the v2 drift policy (alarm + two weekly follow-up retrains)?
**Context:** On the dev set the plain "retrain when drift fires" policy retrained once and went quiet. For a new fraud pattern, labels arrive over weeks, so one retrain could not learn it, and it lost to weekly retraining (61.6% vs 65.5% fraud caught after drift). Adding two weekly follow-up retrains after an alarm fixes the cause. This was decided on dev data only, before the test set was run. The v1 numbers are kept in `results/archive/dev_v1_summary.md`.
**Recommendation:** keep v2, and say openly in the README that v1 lost and why (it is a good story).
**Meanwhile:** froze v2 for the test set.
