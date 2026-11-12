"""Tiny Kubernetes helpers: submit and watch Argo Workflows."""

from __future__ import annotations

import time

NAMESPACE = "fml"


def custom_api():
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CustomObjectsApi()


def submit_retrain(run: str, day: int, seed: int, reason: str) -> str:
    body = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "generateName": f"retrain-d{day:03d}-",
            "labels": {"project": "fraud-model-lifecycle", "fml/run": run[:63]},
        },
        "spec": {
            "workflowTemplateRef": {"name": "retrain"},
            "arguments": {
                "parameters": [
                    {"name": "run", "value": run},
                    {"name": "day", "value": str(day)},
                    {"name": "seed", "value": str(seed)},
                    {"name": "reason", "value": reason},
                ]
            },
        },
    }
    wf = custom_api().create_namespaced_custom_object(
        "argoproj.io", "v1alpha1", NAMESPACE, "workflows", body
    )
    return wf["metadata"]["name"]


def workflow(name: str) -> dict:
    return custom_api().get_namespaced_custom_object(
        "argoproj.io", "v1alpha1", NAMESPACE, "workflows", name
    )


def workflow_phase(name: str) -> str:
    return workflow(name).get("status", {}).get("phase", "Pending")


def running_step(name: str) -> str | None:
    """Display name of the step that is currently running, if any."""
    nodes = workflow(name).get("status", {}).get("nodes", {}) or {}
    running = [
        n.get("displayName")
        for n in nodes.values()
        if n.get("type") == "Pod" and n.get("phase") == "Running"
    ]
    return running[0] if running else None


def wait_workflow(name: str, until_step: str | None = None, timeout_s: int = 1800) -> str:
    """Block until the workflow finishes, or until `until_step` starts running."""
    end = time.time() + timeout_s
    while time.time() < end:
        phase = workflow_phase(name)
        if phase in ("Succeeded", "Failed", "Error"):
            return phase
        if until_step and running_step(name) == until_step:
            return "Running"
        time.sleep(3)
    raise TimeoutError(f"workflow {name} still running after {timeout_s}s")
