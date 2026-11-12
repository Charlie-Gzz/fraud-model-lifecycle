# Slides outline (7 slides)

1. **The problem: fraud changes, models go stale.** A model trained last month quietly misses new fraud. Labels arrive days later, so you cannot just watch accuracy. *Asset:* `assets/charts/scenario_check_test.png` (the three drifts switching on).

2. **What I built.** One local Kubernetes cluster, set up by Terraform: scorer behind a canary, drift monitor, retraining pipeline, model registry, dashboards. *Asset:* `assets/diagrams/architecture.png`.

3. **One model's life, hands-off.** Drift alarm, retrain, gate, canary 20/50/100%, promoted; every step recorded. *Asset:* `assets/screenshots/timeline_event_detail.png` (and the GIF in the README).

4. **Safety rails.** Promotion gate on a recent holdout; Prometheus canary analysis; a deliberately broken model rolled back by itself in 52 seconds. *Asset:* `assets/screenshots/argo_rollouts_canary.png`, `results/cluster/broken_model_rollback.json`.

5. **The experiment.** No retraining vs weekly vs drift-triggered, 4 test scenarios x 5 seeds, settings frozen on dev first. *Asset:* `assets/charts/fraud_caught_over_time.png`.

6. **Result: same catch, far fewer retrains.** 14 retrains vs 40 across the scenarios; 0 on the no-drift control vs 10. *Asset:* `assets/charts/retrains_per_policy.png`.

7. **Where it did not help, and why.** A new fraud pattern barely moves the inputs; it is only caught by the recall drop on late labels, and neither policy wins back more than 13% of the lost catch. Next steps: faster label proxies, a label-free performance estimate. *Asset:* `assets/charts/drift_score_at_detection.png`, `assets/charts/detect_and_recover.png`.
