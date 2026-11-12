"""Download pinned, checksum-verified CLI tools into .tools/ (no admin rights needed)."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import tomllib
import zipfile
from pathlib import Path

import httpx

from fml import REPO_ROOT

TOOLS_DIR = REPO_ROOT / ".tools"
TOOLS_FILE = REPO_ROOT / "infra" / "tools.toml"


def load_specs() -> dict[str, dict]:
    return tomllib.loads(TOOLS_FILE.read_text())


def tool_path(name: str) -> Path:
    return TOOLS_DIR / load_specs()[name]["exe"]


def _extract(spec: dict, payload: bytes) -> bytes:
    url = spec["url"]
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            return zf.read(spec["archive_member"])
    if url.endswith(".gz"):
        return gzip.decompress(payload)
    return payload


def install(name: str, spec: dict, force: bool = False) -> Path:
    target = TOOLS_DIR / spec["exe"]
    stamp = TOOLS_DIR / f"{spec['exe']}.version"
    if target.exists() and not force and stamp.exists() and stamp.read_text() == spec["version"]:
        return target
    TOOLS_DIR.mkdir(exist_ok=True)
    resp = httpx.get(spec["url"], follow_redirects=True, timeout=300)
    resp.raise_for_status()
    digest = hashlib.sha256(resp.content).hexdigest()
    if digest != spec["sha256"]:
        raise RuntimeError(f"{name}: checksum mismatch (got {digest}, want {spec['sha256']})")
    target.write_bytes(_extract(spec, resp.content))
    stamp.write_text(spec["version"])
    return target


def install_all(force: bool = False) -> dict[str, Path]:
    return {name: install(name, spec, force) for name, spec in load_specs().items()}


def tool_env() -> dict[str, str]:
    """Environment with .tools/ first on PATH (kubectl plugins are found this way)."""
    env = dict(os.environ)
    env["PATH"] = str(TOOLS_DIR) + os.pathsep + env.get("PATH", "")
    return env
