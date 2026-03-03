"""
Eisla -- FreeRouting wrapper (python/freeroute.py)

Routes a DSN file using either:
  1. Local FreeRouting jar (default if jar exists)
  2. FreeRouting cloud API (if FREEROUTING_API_KEY is set, or jar missing)

Input (in job_dir):
  board.dsn

Output (in job_dir):
  board.ses

Usage:
    python freeroute.py <job_dir> [--api]

Environment:
    FREEROUTING_JAR       path to freerouting.jar (default: ./freerouting/freerouting.jar)
    FREEROUTING_API_KEY   API key for api.freerouting.app (enables cloud routing)
    FREEROUTING_MAX_PASSES  max autorouter passes (default: 20)
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

FR_JAR = Path(os.environ.get(
    "FREEROUTING_JAR",
    str(PROJECT_ROOT / "freerouting" / "freerouting.jar"),
))
FR_MAX_PASSES = int(os.environ.get("FREEROUTING_MAX_PASSES", "20"))
FR_TIMEOUT = int(os.environ.get("FREEROUTING_TIMEOUT", "90"))


def route_local(dsn_path, ses_path):
    """Route using local FreeRouting jar."""
    java = os.environ.get("JAVA_BIN", "java")
    cmd = [
        java, "-jar", str(FR_JAR),
        "-de", str(dsn_path),
        "-do", str(ses_path),
        "-mp", str(FR_MAX_PASSES),
        "-mt", "1",
    ]
    print(f"[freeroute] Running local jar (max {FR_MAX_PASSES} passes) ...")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=FR_TIMEOUT,
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")
    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            print(f"  {line}")
    if not ses_path.exists():
        print("ERROR: FreeRouting did not produce board.ses")
        sys.exit(1)
    size_kb = ses_path.stat().st_size // 1024
    print(f"[freeroute] board.ses written ({size_kb} KB)")


def route_api(dsn_path, ses_path):
    """Route using FreeRouting cloud API."""
    try:
        from freerouting import FreeroutingClient
    except ImportError:
        print("ERROR: freerouting-client not installed. Run: pip install freerouting-client")
        sys.exit(1)

    api_key = os.environ.get("FREEROUTING_API_KEY")
    if not api_key:
        print("ERROR: FREEROUTING_API_KEY not set")
        sys.exit(1)

    client = FreeroutingClient(api_key=api_key)

    # Check API health
    status = client.get_system_status()
    if status.get("status") != "OK":
        print(f"WARNING: FreeRouting API status: {status}")

    print(f"[freeroute] Submitting to FreeRouting API ...")
    import base64
    output = client.run_routing_job(
        name=dsn_path.stem,
        dsn_file_path=str(dsn_path),
        settings={"router_passes": FR_MAX_PASSES},
        poll_interval=5,
        timeout=FR_TIMEOUT,
    )

    if not output or "data" not in output:
        print("ERROR: FreeRouting API returned no data")
        sys.exit(1)

    with open(ses_path, "wb") as f:
        f.write(base64.b64decode(output["data"]))

    size_kb = ses_path.stat().st_size // 1024
    print(f"[freeroute] board.ses written ({size_kb} KB) via API")


def main():
    if len(sys.argv) < 2:
        print("Usage: python freeroute.py <job_dir> [--api]")
        sys.exit(1)

    job_dir = Path(sys.argv[1])
    use_api = "--api" in sys.argv

    dsn_path = job_dir / "board.dsn"
    ses_path = job_dir / "board.ses"

    if not dsn_path.exists():
        print(f"ERROR: board.dsn not found in {job_dir}")
        sys.exit(1)

    # Decide routing method
    has_jar = FR_JAR.exists()
    has_api_key = bool(os.environ.get("FREEROUTING_API_KEY"))

    if use_api or (not has_jar and has_api_key):
        route_api(dsn_path, ses_path)
    elif has_jar:
        route_local(dsn_path, ses_path)
    else:
        print("ERROR: No routing method available.")
        print(f"  Local jar not found at: {FR_JAR}")
        print("  Set FREEROUTING_API_KEY for cloud routing, or install freerouting.jar")
        sys.exit(1)


if __name__ == "__main__":
    main()
