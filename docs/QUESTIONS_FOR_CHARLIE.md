# Questions for Charlie

Each question has my recommendation and what I did in the meantime. None of these blocked the build.

**Answered 2026-11-13: Charlie accepted all recommendations.** Nothing needed to change; the repo already follows each one.

## 1. SeaweedFS instead of MinIO for object storage?
**Decision (2026-11-13):** recommendation accepted.
**Context:** MinIO stopped publishing container images (Docker Hub and Quay both return "not found" for every tag). The plan's fallback was a local PersistentVolume, which would have changed every storage code path.
**Recommendation:** keep SeaweedFS. It is Apache-2.0, speaks the S3 API, and nothing in the code is SeaweedFS-specific (boto3 + an endpoint URL), so swapping back to any S3 store is a one-line change.
**Meanwhile:** built everything on SeaweedFS; README and diagrams say "S3 object store (SeaweedFS)".

## 2. Keep the final drift policy (v3)?
**Decision (2026-11-13):** recommendation accepted.
**Context:** Two design rounds on the dev set only. v1 ("retrain when 25% of features drift") retrained once and went quiet, and lost to weekly retraining on the new fraud pattern (61.6% vs 65.5% caught). v2 added "any feature drifts" plus two weekly follow-up retrains, but raised 4-17 false alarms per run because `is_new_merchant` crept up as simulated histories filled. v3 uses `new_merchant_7d` (stationary) and needs 3 days of persistent drift. All three dev tables are in `results/archive/`. The test set was only run after v3 was frozen.
**Recommendation:** keep v3, and tell the v1 to v3 story openly in the README (it is the most useful part for a reviewer).
**Meanwhile:** v3 frozen and used for the test set and the full loops.

## 3. Frame the headline as "same catch, far fewer retrains"?
**Decision (2026-11-13):** recommendation accepted.
**Context:** On the test scenarios drift-triggered retraining never beat weekly retraining on fraud caught (within 0.3 points in every scenario), but it needed 14 retrains instead of 40 and none at all on the no-drift control. On the new fraud pattern both policies only won back 13% of the lost catch, because the pattern barely moves the inputs and its labels arrive late.
**Recommendation:** lead with the cost result ("same catch, 65% fewer retrains, zero when nothing changed") and state the new-pattern limit plainly. Do not tune anything further to make drift-triggered "win": the test set has been seen.
**Meanwhile:** README, site, card and slides use this framing.

## 4. Should the scam pattern be made easier to catch?
**Decision (2026-11-13):** recommendation accepted.
**Context:** The concept-drift scenario is hard on purpose (own device, daytime, normal-ish amounts). A louder pattern would make retraining look better, but changing it now would mean re-running the test set after seeing it.
**Recommendation:** no. If you want a "retraining clearly wins" demo, add a separate, clearly labeled scenario later, evaluated on fresh seeds.
**Meanwhile:** left as is.

## 5. Image sizes
**Decision (2026-11-13):** recommendation accepted.
**Context:** Images are large for a laptop demo: runtime 1.8 GB (Evidently, MLflow client, LightGBM, pandas), Spark 1.9 GB (JRE + PySpark), MLflow 1.4 GB. The Spark image was already slimmed from 3.0 GB.
**Recommendation:** fine for now. A later pass could split the scorer (no Evidently) from the monitor/trainer image to save about 0.6 GB.
**Meanwhile:** one shared runtime image, documented.
