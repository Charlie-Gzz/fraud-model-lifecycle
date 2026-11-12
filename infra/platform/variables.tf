variable "kubeconfig_path" {
  description = "Kubeconfig written by the cluster stage."
  type        = string
}

variable "postgres_password" {
  type      = string
  sensitive = true
}

variable "s3_access_key" {
  type      = string
  sensitive = true
}

variable "s3_secret_key" {
  type      = string
  sensitive = true
}

variable "grafana_admin_password" {
  type      = string
  sensitive = true
}
