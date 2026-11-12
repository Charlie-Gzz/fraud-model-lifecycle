# Stage 2: everything that runs inside the kind cluster.
# Third-party charts are pinned to exact versions from their official repos.

terraform {
  required_version = ">= 1.9"
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "3.3.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "3.5.0"
    }
  }
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}

provider "helm" {
  kubernetes = {
    config_path = var.kubeconfig_path
  }
}

locals {
  labels = { project = "fraud-model-lifecycle" }
  values = "${path.module}/values"
}

resource "kubernetes_namespace_v1" "ns" {
  for_each = toset(["fml", "monitoring", "argo", "argo-rollouts"])
  metadata {
    name   = each.key
    labels = local.labels
  }
}

# --- Secrets (values come from .env via TF_VAR_*, never from files in git) ---

resource "kubernetes_secret_v1" "fml" {
  metadata {
    name      = "fml-secrets"
    namespace = "fml"
    labels    = local.labels
  }
  data = {
    POSTGRES_PASSWORD     = var.postgres_password
    AWS_ACCESS_KEY_ID     = var.s3_access_key
    AWS_SECRET_ACCESS_KEY = var.s3_secret_key
  }
  depends_on = [kubernetes_namespace_v1.ns]
}

resource "kubernetes_secret_v1" "s3_config" {
  metadata {
    name      = "seaweedfs-s3-config"
    namespace = "fml"
    labels    = local.labels
  }
  data = {
    "s3.json" = jsonencode({
      identities = [{
        name        = "fml"
        credentials = [{ accessKey = var.s3_access_key, secretKey = var.s3_secret_key }]
        actions     = ["Admin", "Read", "Write", "List", "Tagging"]
      }]
    })
  }
  depends_on = [kubernetes_namespace_v1.ns]
}

resource "kubernetes_secret_v1" "grafana_admin" {
  metadata {
    name      = "grafana-admin"
    namespace = "monitoring"
    labels    = local.labels
  }
  data = {
    admin-user     = "admin"
    admin-password = var.grafana_admin_password
  }
  depends_on = [kubernetes_namespace_v1.ns]
}

# --- Monitoring: Prometheus, Grafana, Alertmanager ---

resource "helm_release" "kube_prometheus_stack" {
  name       = "kps"
  namespace  = "monitoring"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = "92.16.0"
  values     = [file("${local.values}/kube-prometheus-stack.yaml")]
  timeout    = 900
  depends_on = [kubernetes_secret_v1.grafana_admin]
}

# --- Argo Workflows (retraining pipeline) and Argo Rollouts (canary) ---

resource "helm_release" "argo_workflows" {
  name       = "argo-workflows"
  namespace  = "argo"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-workflows"
  version    = "2.0.14"
  values     = [file("${local.values}/argo-workflows.yaml")]
  timeout    = 600
  depends_on = [kubernetes_namespace_v1.ns]
}

resource "helm_release" "argo_rollouts" {
  name       = "argo-rollouts"
  namespace  = "argo-rollouts"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-rollouts"
  version    = "2.43.9"
  values     = [file("${local.values}/argo-rollouts.yaml")]
  timeout    = 600
  depends_on = [kubernetes_namespace_v1.ns]
}

# --- Our data services: S3 object store, Postgres, Redis, MLflow (local chart) ---

resource "helm_release" "fml_platform" {
  name      = "fml-platform"
  namespace = "fml"
  chart     = "${path.module}/../charts/fml-platform"
  values    = [file("${local.values}/fml-platform.yaml")]
  timeout   = 600
  depends_on = [
    kubernetes_secret_v1.fml,
    kubernetes_secret_v1.s3_config,
    helm_release.kube_prometheus_stack, # for the ServiceMonitor CRD
  ]
}
