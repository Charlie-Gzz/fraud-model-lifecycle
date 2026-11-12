# MLflow tracking server with the Postgres driver and S3 client it needs.
FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

LABEL project=fraud-model-lifecycle
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1

RUN pip install mlflow==3.18.0 "psycopg[binary]==3.3.9" boto3==1.44.1 \
    && useradd --create-home --uid 1000 mlflow

USER 1000
EXPOSE 5000
