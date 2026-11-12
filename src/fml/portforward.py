"""Keep one `kubectl port-forward` alive on 127.0.0.1, restarting it if the pod changes.

Started detached by `fml up`; its PID is tracked in .run/port-forwards.json and
stopped by `fml down`.
"""

import subprocess
import sys
import time

from fml.tools import tool_path


def main() -> None:
    kubeconfig, ns, svc, local_port, svc_port = sys.argv[1:6]
    cmd = [
        str(tool_path("kubectl")),
        "--kubeconfig",
        kubeconfig,
        "port-forward",
        "-n",
        ns,
        "--address",
        "127.0.0.1",
        f"svc/{svc}",
        f"{local_port}:{svc_port}",
    ]
    while True:
        subprocess.call(cmd)
        time.sleep(2)


if __name__ == "__main__":
    main()
