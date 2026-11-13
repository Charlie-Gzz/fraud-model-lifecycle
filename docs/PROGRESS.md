# Progress

## Status
- **M0 Setup:** done. Private repo pushed.
- **M1 Platform up:** done. Clean `fml down` (14 s) then `fml up` from scratch: 16 min including first image builds, all 9 services healthy, 4.0 GB idle.
- **M2 Data generator:** done. `assets/charts/scenario_check_{dev,test}.png`.
- **M3 Features + parity:** done. Spark job runs in the cluster; parity on 172,045 transactions, max diff 1.8e-12 (first run, before the `new_merchant_7d` change; rerun pending).
- **M4 Training + registry:** done. Bootstrap model registered in MLflow with alias `champion`, model-card tags.
- **M5 Serving + canary:** done. Canary 20/50/100 promoted v1; broken model (schema mismatch) rolled back automatically in 52 s by the error-rate analysis (`results/cluster/broken_model_rollback.json`). Load test 424 req/s, p95 67 ms (`results/cluster/loadtest.json`).
- **M6/M7:** monitor + workflow + replay written and run end to end for 37 days. Full 110-day dev run in progress (`.run/demo2.log`).
- **M8:** config frozen after dev v3; test set done (60 runs, `results/summary_test.md`). Full loops on the cluster in progress.
- **M9:** site (index/results), charts, architecture diagram (done, reviewed), screenshot/video script written; nothing final yet.

## Log
- 2026-11-12: Environment checked (see DECISIONS). Tools pinned in `infra/tools.toml`.
- 2026-11-12: MinIO images gone; SeaweedFS instead. MLflow job runner disabled (OOM).
- 2026-11-12: Dev v1 → v2 (bootstrap day 35, 110-day scenarios, per-feature alarm, follow-ups). v2 → v3: `is_new_merchant` redefined as `new_merchant_7d` (stationary) and data drift must persist 3 days (v2 had 4-17 false alarms before drift on every dev seed).
- 2026-11-12: Policy chart colours validated with the dataviz palette validator (dark surface).

- 2026-11-12: test/new_fraud_pattern full loop (34 min): same decisions as the backtest (alarm, retrain, gate fail, promotion), each one simulated day earlier; fraud caught after drift 56.6% vs 56.5%.
- 2026-11-12: **Bug found by the full loop:** the monitor service saved its policy state only when it started a retrain, so the 3-day drift streak reset every day and data-drift alarms never fired on the cluster (test/new_category ran 110 days with no alarm while the backtest alarmed on day 73). The new-pattern run was unaffected (its alarm is the recall drop, which needs no streak). Fixed (state saved every day), regression test `tests/test_monitor_state.py`, invalid run deleted, new_category / amount_drift / control rerun.
- 2026-11-12: Test set run (60 backtests, frozen config). Full loops for the 4 test scenarios (seed 201) running via `scripts/run_fullloops.sh`.
- 2026-11-12: **Incident during test/new_fraud_pattern full loop:** I re-applied `k8s/` to update the Grafana dashboard, which reset the Rollout to MODEL_VERSION=none and started a canary to warm-up mode around simulated day 91. Restored the champion (v6) within about a minute. The paused canary pod never served traffic: the run's daily `served_by` counts contain only real model versions (no warm-up rows), so the run is unaffected. `fml apply` now keeps the live model version.

## Next step
1. Wait for `scripts/run_fullloops.sh` (log: `.run/fullloops.log`) to finish all 4 test scenarios; each is collected into `results/fullloop/`.
2. `uv run fml assets` (charts, agreement table, site data), then `uv run fml screens site` and `uv run fml screens cluster --workflow <a drift retrain workflow>`; review every image.
3. `uv run fml screens video` (while Grafana still has recent data).
4. Fill README placeholders (HERO, HEADLINE, RESULTS, COST), write HANDOFF, final secret scan, fresh-clone quickstart check, `fml down`.
