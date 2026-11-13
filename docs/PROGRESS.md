# Progress

## Status
- **M0 Setup:** done. Private repo pushed.
- **M1 Platform up:** done. Clean `fml down` (14 s) then `fml up` from scratch: 16 min including first image builds, all 9 services healthy, 4.0 GB idle.
- **M2 Data generator:** done. `assets/charts/scenario_check_{dev,test}.png`.
- **M3 Features + parity:** done. Spark job runs in the cluster; parity on 172,045 transactions, max diff 1.8e-12 (first run, before the `new_merchant_7d` change; rerun pending).
- **M4 Training + registry:** done. Bootstrap model registered in MLflow with alias `champion`, model-card tags.
- **M5 Serving + canary:** done. Canary 20/50/100 promoted v1; broken model (schema mismatch) rolled back automatically in 52 s by the error-rate analysis (`results/cluster/broken_model_rollback.json`). Load test 424 req/s, p95 67 ms (`results/cluster/loadtest.json`).
- **M6/M7:** done. All four test scenarios ran hands-off on the cluster (drift -> retrain -> gate -> canary -> promoted; control: no retrains). Alerts and dashboard in `k8s/`.
- **M8:** done. 60 test backtests, full loops agree within 0.9 points (`results/fullloop/agreement.md`), `fml results` regenerates every number without a cluster (also in CI).
- **M9:** done. Site, charts, screenshots, video + GIF, diagram, DEMO_SCRIPT, SLIDES_OUTLINE, PORTFOLIO_CARD.
- **M10:** done. README, HANDOFF, secret scan (history clean, no tracked-file findings), repo description and topics, fresh-clone quickstart verified (19 min), cluster deleted with `fml down`.
- **Stretch:** 2 (label-free estimate) and 3 (cloud-ready Terraform layout, validate only) done; 1 (shadow mode) skipped, see HANDOFF.

## Log
- 2026-11-12: Environment checked (see DECISIONS). Tools pinned in `infra/tools.toml`.
- 2026-11-12: MinIO images gone; SeaweedFS instead. MLflow job runner disabled (OOM).
- 2026-11-12: Dev v1 → v2 (bootstrap day 35, 110-day scenarios, per-feature alarm, follow-ups). v2 → v3: `is_new_merchant` redefined as `new_merchant_7d` (stationary) and data drift must persist 3 days (v2 had 4-17 false alarms before drift on every dev seed).
- 2026-11-12: Policy chart colours validated with the dataviz palette validator (dark surface).

- 2026-11-12: test/new_fraud_pattern full loop (34 min): same decisions as the backtest (alarm, retrain, gate fail, promotion), each one simulated day earlier; fraud caught after drift 56.6% vs 56.5%.
- 2026-11-12: **Bug found by the full loop:** the monitor service saved its policy state only when it started a retrain, so the 3-day drift streak reset every day and data-drift alarms never fired on the cluster (test/new_category ran 110 days with no alarm while the backtest alarmed on day 73). The new-pattern run was unaffected (its alarm is the recall drop, which needs no streak). Fixed (state saved every day), regression test `tests/test_monitor_state.py`, invalid run deleted, new_category / amount_drift / control rerun.
- 2026-11-12: Test set run (60 backtests, frozen config). Full loops for the 4 test scenarios (seed 201) running via `scripts/run_fullloops.sh`.
- 2026-11-12: **Incident during test/new_fraud_pattern full loop:** I re-applied `k8s/` to update the Grafana dashboard, which reset the Rollout to MODEL_VERSION=none and started a canary to warm-up mode around simulated day 91. Restored the champion (v6) within about a minute. The paused canary pod never served traffic: the run's daily `served_by` counts contain only real model versions (no warm-up rows), so the run is unaffected. `fml apply` now keeps the live model version.

- 2026-11-13: At Charlie's request the repo was made **public**. Generated reports and charts marked `linguist-generated` so the language bar reflects the code (GitHub was counting 227 MB of Evidently HTML). README verified on GitHub: all 9 images served. Pages not enabled yet.

- 2026-11-13: Charlie accepted all five recommendations; recorded in QUESTIONS, HANDOFF and DECISIONS. No code changes needed.

## Next step
- Open: enabling GitHub Pages (workflow `pages.yml` is ready, manual trigger), only when Charlie asks.
- To bring everything back: `uv run fml up` (images are cached), then `uv run fml demo`.
