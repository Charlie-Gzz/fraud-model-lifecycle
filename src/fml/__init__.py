"""fml: a fraud model's lifecycle on a local Kubernetes cluster."""

import os
from pathlib import Path

__version__ = "0.1.0"

# In containers the package is installed into a venv, so the image sets FML_ROOT.
REPO_ROOT = Path(os.environ.get("FML_ROOT") or Path(__file__).resolve().parents[2])
