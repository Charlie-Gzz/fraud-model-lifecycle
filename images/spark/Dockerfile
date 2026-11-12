# PySpark in local mode for the batch feature job. Java lives only in this image.
# Slim on purpose: only what the Spark step imports (versions match uv.lock), plus the
# fml source on PYTHONPATH without its other dependencies.
FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

LABEL project=fraud-model-lifecycle
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends openjdk-21-jre-headless procps \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 fml
RUN pip install pyspark==4.3.0 pandas==2.3.3 pyarrow==26.0.1 numpy==2.5.4 boto3==1.44.2 pyyaml==6.0.3 \
    && rm -rf /usr/local/lib/python3.12/site-packages/pyspark/examples \
              /usr/local/lib/python3.12/site-packages/pyspark/data

COPY src /app/src
COPY scenarios /app/scenarios
COPY configs /app/configs
ENV PYTHONPATH=/app/src FML_ROOT=/app PYTHONUNBUFFERED=1 \
    JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 PYSPARK_PYTHON=/usr/local/bin/python
WORKDIR /app
USER 1000
