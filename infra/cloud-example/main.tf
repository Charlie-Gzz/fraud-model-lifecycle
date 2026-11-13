# Stretch 3: the same platform code pointed at a managed Kubernetes cluster.
#
# VALIDATE ONLY. Never run `terraform apply` here: this project creates no cloud
# resources. It shows that infra/platform does not depend on kind; only the cluster
# stage changes. Check with:
#   terraform -chdir=infra/cloud-example init -backend=false
#   terraform -chdir=infra/cloud-example validate

terraform {
  required_version = ">= 1.9"
}

variable "kubeconfig_path" {
  description = "Kubeconfig of an existing managed cluster (EKS, GKE, AKS...)."
  type        = string
  default     = "~/.kube/managed-cluster"
}

variable "postgres_password" {
  type      = string
  sensitive = true
  default   = "set-me"
}

variable "s3_access_key" {
  type      = string
  sensitive = true
  default   = "set-me"
}

variable "s3_secret_key" {
  type      = string
  sensitive = true
  default   = "set-me"
}

variable "grafana_admin_password" {
  type      = string
  sensitive = true
  default   = "set-me"
}

# The cluster itself would come from a provider module here, for example
# terraform-aws-modules/eks/aws, with node groups sized from the memory plan (about 10 GB
# for the platform). Left out on purpose: no cloud provider is configured in this repo.

module "platform" {
  source                 = "../platform"
  kubeconfig_path        = pathexpand(var.kubeconfig_path)
  postgres_password      = var.postgres_password
  s3_access_key          = var.s3_access_key
  s3_secret_key          = var.s3_secret_key
  grafana_admin_password = var.grafana_admin_password
}
