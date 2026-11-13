"""Screenshots and the walkthrough video, with headless Chromium (Playwright).

Everything is opened through the 127.0.0.1 port-forwards or a local static server.
No logins are needed (Grafana anonymous viewer, Argo server auth mode), so no
credentials ever appear on screen.

    uv run python -m fml.viz.screens site          # site screens (no cluster needed)
    uv run python -m fml.viz.screens cluster       # Grafana, Argo, MLflow (cluster up)
    uv run python -m fml.viz.screens canary        # waits for a canary, then captures it
    uv run python -m fml.viz.screens video         # site walkthrough + Grafana -> MP4/GIF
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import subprocess
import sys
import threading
import time
from pathlib import Path

from fml import REPO_ROOT

OUT = REPO_ROOT / "assets" / "screenshots"
VIDEO = REPO_ROOT / "assets" / "video"
SITE_PORT = 8765
VIEW = {"width": 1600, "height": 1000}
FFMPEG_IMAGE = (
    "linuxserver/ffmpeg:7.1.1"
    "@sha256:aea59a11c54291ac456bb2d67000445e5a8994f70bc3d96cdc29f022fbbf89fb"
)


@contextlib.contextmanager
def serve_site():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(REPO_ROOT / "site")
    )
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", SITE_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{SITE_PORT}"
    finally:
        httpd.shutdown()


@contextlib.contextmanager
def browser(record_video: Path | None = None):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        kw = {"viewport": VIEW, "device_scale_factor": 1, "color_scheme": "dark"}
        if record_video:
            kw["record_video_dir"] = str(record_video)
            kw["record_video_size"] = VIEW
        ctx = b.new_context(**kw)
        try:
            yield ctx
        finally:
            ctx.close()
            b.close()


def shot(page, name: str, full: bool = False) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    print(f"saved {path.relative_to(REPO_ROOT)}")
    return path


def site_screens() -> None:
    with serve_site() as base, browser() as ctx:
        page = ctx.new_page()
        page.goto(f"{base}/index.html?scenario=new_fraud_pattern", wait_until="networkidle")
        page.wait_for_selector("#chart svg")
        time.sleep(1)
        shot(page, "timeline")
        promoted = page.locator('.marker[aria-label^="Promoted"]')
        # The second promotion is the first drift-triggered one (the first is the bootstrap).
        (promoted.nth(1) if promoted.count() > 1 else page.locator(".marker").first).click()
        time.sleep(0.5)
        shot(page, "timeline_event_detail")
        drift = page.locator('.marker[aria-label^="Drift detected"]')
        if drift.count():
            drift.first.click()
            time.sleep(0.5)
            shot(page, "timeline_drift_detail")
        page.goto(f"{base}/results.html", wait_until="networkidle")
        time.sleep(1)
        shot(page, "policy_comparison")
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{base}/index.html?scenario=new_fraud_pattern", wait_until="networkidle")
        time.sleep(1)
        shot(page, "timeline_mobile")
        reports = sorted((REPO_ROOT / "site" / "reports").glob("*/*.html"))
        # Prefer a report where data drift was found (amount drift, then new category).
        for prefer in ("amount-drift", "new-category"):
            chosen = [r for r in reports if prefer in r.parent.name]
            if chosen:
                reports = chosen
                break
        if reports:
            page.set_viewport_size(VIEW)
            rel = reports[0].relative_to(REPO_ROOT / "site").as_posix()
            page.goto(f"{base}/{rel}", wait_until="networkidle")
            time.sleep(3)
            shot(page, "evidently_report")


def _dismiss(page) -> None:
    """Close first-visit popups (Argo's survey, MLflow's assistant panel)."""
    import re

    for locator in (
        page.get_by_role("button", name=re.compile(r"^(close|×)$", re.I)),
        page.locator("text=×"),
        page.locator("[aria-label='Close'], [aria-label='close']"),
        page.locator(".modal-close"),  # Argo's release-notes popup
    ):
        try:
            if locator.count():
                locator.first.click(timeout=2000)
                time.sleep(0.5)
        except Exception:
            pass
    page.keyboard.press("Escape")
    time.sleep(0.5)


def cluster_screens(workflow: str | None = None) -> None:
    with browser() as ctx:
        page = ctx.new_page()
        page.goto(
            "http://127.0.0.1:3000/d/fraud-lifecycle?orgId=1&kiosk&from=now-30m&to=now",
            wait_until="load",
        )
        time.sleep(6)
        shot(page, "grafana_dashboard")
        page.goto("http://127.0.0.1:5000/#/models/fraud-detector", wait_until="load")
        time.sleep(4)
        _dismiss(page)
        shot(page, "mlflow_model_aliases")
        if workflow:
            page.goto(f"http://127.0.0.1:2746/workflows/fml/{workflow}", wait_until="load")
            time.sleep(5)
            _dismiss(page)
            shot(page, "argo_workflow_graph")
        page.goto("http://127.0.0.1:3100/rollouts/rollout/fml/fraud-scorer", wait_until="load")
        time.sleep(3)
        shot(page, "argo_rollouts")


def canary_screen(timeout_s: int = 3600) -> None:
    """Poll the Rollout until a canary is mid-way, then capture the Rollouts dashboard."""
    import os

    from fml.pipeline import rollout
    from fml.platform import KUBECONFIG

    os.environ["KUBECONFIG"] = str(KUBECONFIG)
    end = time.time() + timeout_s
    while time.time() < end:
        st = rollout.get_rollout().get("status", {})
        if st.get("phase") in ("Paused", "Progressing") and (st.get("currentStepIndex") or 0) >= 2:
            with browser() as ctx:
                page = ctx.new_page()
                page.goto(
                    "http://127.0.0.1:3100/rollouts/rollout/fml/fraud-scorer",
                    wait_until="networkidle",
                )
                time.sleep(3)
                shot(page, "argo_rollouts_canary")
                page.goto(
                    "http://127.0.0.1:3000/d/fraud-lifecycle?orgId=1&kiosk&from=now-15m&to=now",
                    wait_until="networkidle",
                )
                time.sleep(6)
                shot(page, "grafana_during_canary")
            return
        time.sleep(2)
    print("no canary seen before timeout")


def ffmpeg(args: list[str], workdir: Path) -> None:
    """Run ffmpeg in a container (nothing installed on the host)."""
    image = FFMPEG_IMAGE
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--label",
            "project=fraud-model-lifecycle",
            "-v",
            f"{workdir}:/work",
            "-w",
            "/work",
            image,
            *args,
        ],
        check=True,
    )


def video(with_grafana: bool = True) -> None:
    raw = VIDEO / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for f in raw.glob("*.webm"):
        f.unlink()
    with serve_site() as base, browser(record_video=raw) as ctx:
        page = ctx.new_page()
        page.goto(f"{base}/index.html?scenario=new_fraud_pattern", wait_until="networkidle")
        time.sleep(3)
        box = page.locator("#chart").bounding_box()
        for i in range(0, 40):
            page.mouse.move(box["x"] + 60 + i * (box["width"] - 80) / 40, box["y"] + 120)
            time.sleep(0.12)
        markers = page.locator(".marker")
        # The drift episode: first alarm, then its gate and promotion (index 0 of those
        # is the bootstrap model, so take the second when there is one).
        for label, idx in (("Drift detected", 0), ("Gate passed", 1), ("Promoted", 1)):
            m = page.locator(f'.marker[aria-label^="{label}"]')
            if m.count():
                target = m.nth(min(idx, m.count() - 1))
                target.hover()
                time.sleep(0.8)
                target.click()
                time.sleep(2.5)
        _ = markers
        for sc in ("new_category", "amount_drift", "control"):
            page.locator(
                ".tab",
                has_text={
                    "new_category": "category",
                    "amount_drift": "Amounts",
                    "control": "Control",
                }[sc],
            ).first.click()
            time.sleep(2.5)
        page.goto(f"{base}/results.html", wait_until="networkidle")
        time.sleep(2)
        for _ in range(12):
            page.mouse.wheel(0, 400)
            time.sleep(0.5)
        if with_grafana:
            page.goto(
                "http://127.0.0.1:3000/d/fraud-lifecycle?orgId=1&kiosk&from=now-30m&to=now",
                wait_until="networkidle",
            )
            time.sleep(8)
    webm = max(raw.glob("*.webm"), key=lambda p: p.stat().st_mtime)
    webm.rename(raw / "walkthrough.webm")
    VIDEO.mkdir(exist_ok=True)
    ffmpeg(
        [
            "-y",
            "-i",
            "raw/walkthrough.webm",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            "walkthrough.mp4",
        ],
        VIDEO,
    )
    ffmpeg(
        [
            "-y",
            "-ss",
            "2",
            "-t",
            "14",
            "-i",
            "raw/walkthrough.webm",
            "-vf",
            "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];"
            "[b][p]paletteuse=dither=bayer",
            "walkthrough.gif",
        ],
        VIDEO,
    )
    print("saved assets/video/walkthrough.mp4 and walkthrough.gif")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "site"
    {
        "site": site_screens,
        "cluster": lambda: cluster_screens(sys.argv[2] if len(sys.argv) > 2 else None),
        "canary": canary_screen,
        "video": video,
    }[what]()
