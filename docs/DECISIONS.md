# Decisions

Choices a reviewer might question. Newest at the bottom of each section.

## Setup and tooling

| Decision | Options considered | Why | Easy to change? |
|---|---|---|---|
| Docker memory recorded at M0: 15.6 GB, 12 CPUs. Normal profile, but the platform is still sized to fit in 10 GB. | slim profile, normal profile | Docker has more than 10 GB, so Section 1.3 says normal profile. Limits still add up to under 10 GB. | yes |
| CLI tool versions: kind v0.33.0 (node image v1.37.0), kubectl v1.37.2, helm v4.3.1, terraform 1.17.1, argo v4.1.6, kubectl-argo-rollouts v1.10.2. Pinned with SHA-256 in `infra/tools.toml`. | latest of each; releases a few weeks old | Picked the newest release that had been out for a while where possible (terraform 1.17.2 shipped yesterday, so 1.17.1). Checksums come from each project's official checksum file. | yes |
| pandas pinned to 2.3.x, not 3.x | pandas 3.1, pandas 2.3 | Evidently 0.7.23 imports a pandas internal that pandas 3 removed. | yes, once Evidently supports pandas 3 |
| plotly pinned to 5.x | plotly 7.1, plotly 5.24 | Evidently 0.7.23 requires plotly < 6. | yes |
| Product name **Tideline** | Driftwatch, Canary Lane, Tideline | Short, ties to the lifecycle timeline (the star view) and to drift. Teal accent fits water. | yes |
