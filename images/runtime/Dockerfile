# One image for everything Python in the cluster: model service, monitor, trainer, replay.
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS build
COPY --from=uv /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra runtime --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra runtime --no-editable

FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
LABEL project=fraud-model-lifecycle
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 fml
COPY --from=build /app/.venv /app/.venv
COPY scenarios /app/scenarios
ENV PATH=/app/.venv/bin:$PATH FML_ROOT=/app PYTHONUNBUFFERED=1 MLFLOW_DISABLE_AGENT_HINT=1
WORKDIR /app
USER 1000
