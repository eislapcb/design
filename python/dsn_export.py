"""
Eisla -- Specctra DSN Exporter (python/dsn_export.py)

Session 11. Runs after kicad_pcb.py, before FreeRouting.

Converts board.kicad_pcb to board.dsn (Specctra format) using the
pcbnew.ExportSpecctraDSN API. Validates the DSN file before handing
off to FreeRouting.

MUST be run with KiCad's Python interpreter:
  "C:/Program Files/KiCad/9.0/bin/python.exe" dsn_export.py <job_dir>

Input (in job_dir):
  board.kicad_pcb

Output (in job_dir):
  board.dsn
"""

import json
import sys
from pathlib import Path

import pcbnew


def main():
    if len(sys.argv) < 2:
        print("Usage: python dsn_export.py <job_dir>")
        sys.exit(1)

    job_dir = Path(sys.argv[1])
    pcb_path = job_dir / "board.kicad_pcb"
    dsn_path = job_dir / "board.dsn"

    if not pcb_path.exists():
        print(f"ERROR: board.kicad_pcb not found in {job_dir}")
        sys.exit(1)

    print(f"[dsn_export] Loading {pcb_path.name} ...")
    board = pcbnew.LoadBoard(str(pcb_path))

    n_footprints = len(list(board.GetFootprints()))
    n_nets       = board.GetNetCount()
    print(f"[dsn_export] Board has {n_footprints} footprints, {n_nets} nets")

    print(f"[dsn_export] Exporting to {dsn_path.name} ...")
    ok = pcbnew.ExportSpecctraDSN(board, str(dsn_path))

    if not ok or not dsn_path.exists():
        print("ERROR: ExportSpecctraDSN returned failure or file not created")
        sys.exit(1)

    size_kb = dsn_path.stat().st_size // 1024
    if size_kb == 0:
        print("ERROR: board.dsn is empty")
        sys.exit(1)

    # Quick validity check — DSN must start with (pcb
    with open(dsn_path, encoding="utf-8", errors="ignore") as f:
        head = f.read(64).strip()
    if not head.startswith("(pcb"):
        print(f"ERROR: board.dsn does not look like a valid DSN file (starts with: {head[:32]!r})")
        sys.exit(1)

    print(f"[dsn_export] board.dsn written ({size_kb} KB) — ready for FreeRouting")


if __name__ == "__main__":
    main()
