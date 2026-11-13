# Handoff

## What was built
**Tideline**: a fraud model's full lifecycle on a local kind cluster, created by Terraform.
- Seeded synthetic transactions (3,000 users, 110 days, 5 fraud patterns, delayed labels) and four scenarios per set (new fraud pattern, new merchant category, rising amounts, control), with separate dev and test sets.
- One feature definition, three implementations (PySpark for training, Redis for serving, numpy for the backtest), checked against each other on every retrain.
- LightGBM training with time-based windows, a promotion gate on recent settled labels, MLflow registry with model cards and `champion` / `challenger` aliases.
- FastAPI scorer behind an Argo Rollouts canary (20/50/100% of pods) with Prometheus analysis and automatic rollback.
- Evidently drift monitor + delayed-label recall, Grafana dashboard, alert rules, and an Argo Workflows retraining pipeline triggered by the monitor.
- A traffic replay that drives everything in simulated days, a fast in-process backtest that shares the same code, and a policy comparison (no retraining vs weekly vs drift-triggered).
- Results site (timeline star view + policy comparison + interactive Plotly page), charts, screenshots, walkthrough video, architecture diagram, slides outline, portfolio card.

## How to run it
```bash
uv sync
uv run fml up      # kind cluster + platform + images (about 15 min the first time)
uv run fml demo    # one scenario end to end (about 30 min)
uv run fml down    # delete the cluster (images stay for a fast restart)
```
No cluster needed: `uv run fml results` recomputes every number, `uv run fml assets` redraws charts and the site, `uv run fml backtest --set test` reruns the comparison (resumable).

## Headline numbers (test scenarios, 5 seeds, fast backtest)
<!-- HEADLINE -->

<!-- NUMBERS -->

## Where the assets are
- Charts (PNG 1600px + SVG): `assets/charts/`
- Screenshots: `assets/screenshots/`
- Video and GIF: `assets/video/walkthrough.mp4`, `assets/video/walkthrough.gif`
- Architecture diagram: `assets/diagrams/architecture.svg` / `.png`
- Site: `site/` (open `site/index.html` through any static server; GitHub Pages workflow prepared, not enabled)
- Results: `results/summary_test.md`, `results/backtest/`, `results/fullloop/`, `results/cluster/`
- Docs: `docs/DECISIONS.md`, `docs/QUESTIONS_FOR_CHARLIE.md`, `docs/PROGRESS.md`, `docs/DEMO_SCRIPT.md`, `docs/SLIDES_OUTLINE.md`, `docs/PORTFOLIO_CARD.md`

## Top questions (my recommendation first; details in QUESTIONS_FOR_CHARLIE.md)
1. **SeaweedFS instead of MinIO?** Keep it (MinIO images are gone; any S3 endpoint works).
2. **Keep the final drift policy (v3)?** Yes, and tell the v1 to v3 story openly.
3. **Headline framing?** "Same catch, 65% fewer retrains, zero when nothing changed", with the new-pattern limit stated plainly.
4. **Make the scam pattern easier?** No; the test set has been seen.
5. **Image sizes (1.4 to 1.9 GB each)?** Fine for now; split the scorer image later if it matters.

## Skipped, faked, or changed, and why
- **MinIO → SeaweedFS** (images no longer published). Logged in DECISIONS.
- **Canary weights are pod ratios** (1 of 5 pods = 20%), no service mesh. Documented in Limitations.
- **The simulation clock pauses** while a retraining workflow trains; the canary runs on the next day's traffic at a slower pace.
- **Full-loop runs use one seed per scenario** (201); the 5-seed numbers come from the fast backtest. Both are labeled.
- **Dev results** used an earlier LightGBM seed rule (seed + model version). Dev is tuning only; the test set and full loops use the aligned rule (seed + decision day).
- **One cluster incident and one bug**, both logged in PROGRESS: a manifest re-apply briefly reset the scorer's model version (no traffic was affected), and the monitor did not persist its drift streak (found by the full loop, fixed, regression test added, affected runs rerun).
- Stretch items: <!-- STRETCH -->

## Memory and cost
<!-- MEMORY -->
Cost: $0 (local Docker Desktop only, no cloud, no API keys).

## Secret scan
<!-- SECRETS -->

## Pre-public checklist
1. Read README and HANDOFF; answer the questions.
2. Skim screenshots and video for anything personal.
3. Confirm the secret scan was clean and nothing from your employer appears.
4. Make the repo public, then enable GitHub Pages.
5. Pin the repo on your profile and add it to the portfolio site.
