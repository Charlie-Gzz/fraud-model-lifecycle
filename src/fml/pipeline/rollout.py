"""Drive the Argo Rollouts canary for a new model version and record what happens.

Changing the MODEL_VERSION env var on the Rollout's pod template starts a canary
(20% -> 50% -> 100%). Argo Rollouts runs the Prometheus analysis in the background and
aborts on its own if the canary misbehaves. This step only watches and records.
"""

from __future__ import annotations

import time

from fml import events

GROUP, VERSION, PLURAL = "argoproj.io", "v1alpha1", "rollouts"
NAMESPACE, NAME = "fml", "fraud-scorer"
TIMEOUT_S = 20 * 60


def _api():
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CustomObjectsApi()


def get_rollout(api=None) -> dict:
    return (api or _api()).get_namespaced_custom_object(GROUP, VERSION, NAMESPACE, PLURAL, NAME)


def model_version(ro: dict) -> str:
    env = ro["spec"]["template"]["spec"]["containers"][0].get("env", [])
    return next((e.get("value", "") for e in env if e["name"] == "MODEL_VERSION"), "")


def set_model_version(version: str, api=None) -> None:
    api = api or _api()
    ro = get_rollout(api)
    containers = ro["spec"]["template"]["spec"]["containers"]
    env = [e for e in containers[0].get("env", []) if e["name"] != "MODEL_VERSION"]
    containers[0]["env"] = [*env, {"name": "MODEL_VERSION", "value": str(version)}]
    patch = {"spec": {"template": {"spec": {"containers": containers}}}}
    api.patch_namespaced_custom_object(GROUP, VERSION, NAMESPACE, PLURAL, NAME, patch)


def promote_full(api=None) -> None:
    """Skip the canary steps (used only to reset the service between runs)."""
    api = api or _api()
    api.patch_namespaced_custom_object_status(
        GROUP, VERSION, NAMESPACE, PLURAL, NAME, {"status": {"promoteFull": True}}
    )


def is_healthy(ro: dict) -> bool:
    st = ro.get("status", {})
    return st.get("phase") == "Healthy" and st.get("stableRS") == st.get("currentPodHash")


def wait_healthy(timeout_s: int = 600) -> None:
    api = _api()
    end = time.time() + timeout_s
    while time.time() < end:
        if is_healthy(get_rollout(api)):
            return
        time.sleep(3)
    raise TimeoutError("rollout did not become healthy")


def reset(version: str = "none") -> None:
    """Point the service at `version` without a canary (between full-loop runs)."""
    api = _api()
    if model_version(get_rollout(api)) != version:
        set_model_version(version, api)
        time.sleep(2)
        promote_full(api)
    wait_healthy()


def deploy(run: str, day: int, version: str, workflow: str) -> bool:
    """Canary `version`. Returns True if promoted, False if rolled back."""
    from fml.serve import registry

    api = _api()
    previous = model_version(get_rollout(api))
    set_model_version(version, api)
    steps = get_rollout(api)["spec"]["strategy"]["canary"]["steps"]
    seen_step, end = -1, time.time() + TIMEOUT_S
    while time.time() < end:
        time.sleep(3)
        ro = get_rollout(api)
        st = ro.get("status", {})
        idx = st.get("currentStepIndex", 0) or 0
        if idx != seen_step and idx < len(steps) and "setWeight" in steps[idx]:
            seen_step = idx
            weight = steps[idx]["setWeight"]
            events.emit(
                run,
                day,
                "canary_step",
                "rollout",
                f"v{version} at {weight}% of pods",
                workflow=workflow,
                version=version,
                weight=weight,
            )
        if st.get("abort") or st.get("phase") == "Degraded":
            message = st.get("message", "analysis failed")
            events.emit(
                run,
                day,
                "rolled_back",
                "rollout",
                f"v{version} rolled back: {message}",
                workflow=workflow,
                version=version,
                kept=previous,
            )
            set_model_version(previous, api)  # spec back to the stable version
            wait_healthy()
            return False
        if is_healthy(ro) and model_version(ro) == str(version):
            registry.set_alias(registry.CHAMPION, version)
            registry.client().set_model_version_tag(
                registry.MODEL_NAME, version, "live_from_day", str(day + 1)
            )
            events.emit(
                run,
                day,
                "promoted",
                "rollout",
                f"v{version} is the new champion",
                workflow=workflow,
                version=version,
                previous=previous,
            )
            return True
    raise TimeoutError(f"canary for v{version} did not finish in {TIMEOUT_S}s")
