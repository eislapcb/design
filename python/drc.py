"""
Eisla -- DRC Runner (python/drc.py)

Session 11. Runs after FreeRouting produces board.ses.

Steps:
  1. Load board.kicad_pcb
  2. Import board.ses routing (pcbnew.ImportSpecctraSES)
  3. Save updated board.kicad_pcb (now with routed traces)
  4. Run DRC (pcbnew.WriteDRCReport) -> board.drc_report.txt
  5. Parse report -> drc_report.json
  6. Exit 0 on clean DRC, exit 1 on DRC errors (so worker can flag status)

MUST be run with KiCad's Python interpreter:
  "C:/Program Files/KiCad/9.0/bin/python.exe" drc.py <job_dir>

Input (in job_dir):
  board.kicad_pcb   -- placed, unrouted (or partially routed)
  board.ses         -- FreeRouting output

Output (in job_dir):
  board.kicad_pcb   -- overwritten with routed traces
  drc_report.json   -- parsed DRC results
"""

import json
import re
import sys
from pathlib import Path

import pcbnew


# ─── DRC report parsing ───────────────────────────────────────────────────────

def parse_drc_report(report_path):
    """
    Parse KiCad's text DRC report into a structured dict.

    KiCad 9 report format (relevant sections):
      ** Found N DRC violations **
      [error_type]: description
          @(x mm, y mm): ...

      ** End of Report **

    Returns:
      {
        "error_count":   int,
        "warning_count": int,
        "unrouted_count": int,
        "errors":   [{type, message, location}],
        "warnings": [{type, message, location}],
        "clean":    bool
      }
    """
    text = report_path.read_text(encoding="utf-8", errors="replace")

    errors   = []
    warnings = []
    unrouted = 0

    # Count totals from summary line
    m = re.search(r"(\d+)\s+DRC\s+violations", text, re.IGNORECASE)
    total_violations = int(m.group(1)) if m else 0

    m = re.search(r"(\d+)\s+unconnected\s+items", text, re.IGNORECASE)
    unrouted = int(m.group(1)) if m else 0

    # Parse individual violation blocks
    # KiCad format: "[severity type]: message\n    @(x, y): detail"
    violation_pattern = re.compile(
        r'\[(error|warning)\s+([^\]]+)\]:\s*(.+?)(?=\n\[|\Z)',
        re.IGNORECASE | re.DOTALL
    )
    for match in violation_pattern.finditer(text):
        severity = match.group(1).lower()
        vtype    = match.group(2).strip()
        body     = match.group(3).strip()

        # Extract location if present
        loc_match = re.search(r'@\(([^)]+)\)', body)
        location  = loc_match.group(1).strip() if loc_match else None
        message   = re.split(r'\n\s+@\(', body)[0].strip()

        entry = {"type": vtype, "message": message, "location": location}

        if severity == "error":
            errors.append(entry)
        else:
            warnings.append(entry)

    # Fallback: use total_violations count if regex found nothing
    error_count   = len(errors)   if errors   else (total_violations - len(warnings))
    warning_count = len(warnings)

    return {
        "error_count":    max(error_count, 0),
        "warning_count":  warning_count,
        "unrouted_count": unrouted,
        "errors":         errors,
        "warnings":       warnings,
        "clean":          (error_count == 0 and unrouted == 0),
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python drc.py <job_dir>")
        sys.exit(1)

    job_dir  = Path(sys.argv[1])
    pcb_path = job_dir / "board.kicad_pcb"
    ses_path = job_dir / "board.ses"
    rpt_path = job_dir / "board.drc_report.txt"
    out_path = job_dir / "drc_report.json"

    if not pcb_path.exists():
        print(f"ERROR: board.kicad_pcb not found in {job_dir}")
        sys.exit(1)

    print(f"[drc] Loading {pcb_path.name} ...")
    board = pcbnew.LoadBoard(str(pcb_path))

    # ── Import FreeRouting .ses ────────────────────────────────────────────
    if ses_path.exists():
        print(f"[drc] Importing routing from {ses_path.name} ...")
        ok = pcbnew.ImportSpecctraSES(board, str(ses_path))
        if not ok:
            print("[drc] WARNING: ImportSpecctraSES returned failure — using unrouted board")
        else:
            # Save routed board back to kicad_pcb
            pcbnew.SaveBoard(str(pcb_path), board)
            # Reload to ensure DRC sees the routed state
            board = pcbnew.LoadBoard(str(pcb_path))
            print(f"[drc] Routing imported and board saved")
    else:
        print(f"[drc] WARNING: board.ses not found — running DRC on unrouted board")

    # ── Run DRC ───────────────────────────────────────────────────────────
    print(f"[drc] Running DRC ...")
    pcbnew.WriteDRCReport(board, str(rpt_path), pcbnew.EDA_UNITS_MM, True)

    if not rpt_path.exists():
        print("ERROR: DRC report file was not created")
        sys.exit(1)

    # ── Parse report ──────────────────────────────────────────────────────
    report = parse_drc_report(rpt_path)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────
    status = "CLEAN" if report["clean"] else "VIOLATIONS FOUND"
    print(f"[drc] DRC {status}: "
          f"{report['error_count']} error(s), "
          f"{report['warning_count']} warning(s), "
          f"{report['unrouted_count']} unrouted net(s)")
    print(f"[drc] Report saved to {out_path}")

    # Exit 1 if there are hard DRC errors (warnings are non-fatal)
    if report["error_count"] > 0 or report["unrouted_count"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
