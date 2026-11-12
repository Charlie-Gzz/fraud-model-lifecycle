# Stage 1: the local kind cluster. Nothing here touches any cloud.

terraform {
  required_version = ">= 1.9"
  required_providers {
    kind = {
      source  = "tehcyx/kind"
      version = "0.13.0"
    }
  }
}

variable "kubeconfig_path" {
  description = "Where to write the cluster's kubeconfig (kept out of ~/.kube on purpose)."
  type        = string
}

variable "cluster_name" {
  type    = string
  default = "fml"
}

provider "kind" {}

resource "kind_cluster" "this" {
  name            = var.cluster_name
  node_image      = "kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5"
  kubeconfig_path = var.kubeconfig_path
  wait_for_ready  = true

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    # Single node: everything shares one container, which keeps memory low.
    # No extra_port_mappings: UIs are reached only via kubectl port-forward on 127.0.0.1.
    node {
      role = "control-plane"
    }
  }
}

output "context_name" {
  value = kind_cluster.this.context_name
}
