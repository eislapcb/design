"""
Eisla -- Post-Processing (python/postprocess.py)

Session 12. Runs after DRC (drc.py). Final pipeline stage.

Steps:
  1. Load routed board.kicad_pcb
  2. Export Gerbers (RS-274X) for all copper + mask + silk + outline layers
  3. Export drill file (Excellon)
  4. Generate BOM CSV from placement.json + components.json
  5. Generate pick-and-place CSV from placement.json
  6. Generate DRC_FAILED.txt if drc_report.json has errors
  7. Package everything into output.zip

MUST be run with KiCad's Python interpreter:
  "C:/Program Files/KiCad/9.0/bin/python.exe" postprocess.py <job_dir>

Input (in job_dir):
  board.kicad_pcb          -- routed PCB
  board.kicad_sch          -- schematic
  board.kicad_pro          -- project file
  placement.json           -- component positions
  netlist.json             -- nets
  drc_report.json          -- DRC results
  validation_warnings.json -- design validation warnings

Output (in job_dir):
  gerbers/                 -- Gerber + drill files
  bom.csv
  pick_and_place.csv
  DRC_FAILED.txt           -- only if DRC errors exist
  output.zip               -- everything packaged
"""

import csv
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pcbnew

SCRIPT_DIR      = Path(__file__).parent
PROJECT_ROOT    = SCRIPT_DIR.parent
COMPONENTS_PATH = PROJECT_ROOT / "data" / "components.json"

# Gerber layer mapping: (pcbnew layer ID, file extension, description)
GERBER_LAYERS = [
    (pcbnew.F_Cu,     "GTL", "Top copper"),
    (pcbnew.B_Cu,     "GBL", "Bottom copper"),
    (pcbnew.F_Mask,   "GTS", "Top solder mask"),
    (pcbnew.B_Mask,   "GBS", "Bottom solder mask"),
    (pcbnew.F_SilkS,  "GTO", "Top silkscreen"),
    (pcbnew.B_SilkS,  "GBO", "Bottom silkscreen"),
    (pcbnew.F_Paste,  "GTP", "Top paste"),
    (pcbnew.B_Paste,  "GBP", "Bottom paste"),
    (pcbnew.Edge_Cuts,"GM1", "Board outline"),
]

INNER_LAYERS = [
    (pcbnew.In1_Cu, "G2L", "Inner 1"),
    (pcbnew.In2_Cu, "G3L", "Inner 2"),
    (pcbnew.In3_Cu, "G4L", "Inner 3"),
    (pcbnew.In4_Cu, "G5L", "Inner 4"),
]


def load_json(path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_db():
    with open(COMPONENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


# ─── Gerber export ────────────────────────────────────────────────────────────

def export_gerbers(board, gerber_dir, layer_count=2, pcb_path=None):
    """Export Gerber files via kicad-cli (reliable in KiCad 9 headless mode).

    Falls back to pcbnew PLOT_CONTROLLER if kicad-cli is unavailable.
    """
    os.makedirs(gerber_dir, exist_ok=True)

    kicad_cli = os.environ.get("KICAD_CLI", "C:/Program Files/KiCad/9.0/bin/kicad-cli.exe")
    # Also check without .exe for Linux/macOS
    if not os.path.exists(kicad_cli):
        kicad_cli = kicad_cli.replace(".exe", "")

    if pcb_path and os.path.exists(kicad_cli):
        # ── kicad-cli approach (KiCad 9 recommended) ─────────────────
        # Build layer list
        layers = ["F.Cu", "B.Cu", "F.Mask", "B.Mask", "F.SilkS", "B.SilkS",
                  "F.Paste", "B.Paste", "Edge.Cuts"]
        inner_names = ["In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu"]
        if layer_count > 2:
            layers.extend(inner_names[:min(layer_count - 2, 4)])

        cmd = [str(kicad_cli), "pcb", "export", "gerbers",
               "-o", str(gerber_dir) + "/",
               "-l", ",".join(layers),
               "--no-x2",
               "--subtract-soldermask",
               str(pcb_path)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[postprocess] kicad-cli gerber export failed: {result.stderr}")

        # Also export drill files via kicad-cli
        drill_cmd = [str(kicad_cli), "pcb", "export", "drill",
                     "-o", str(gerber_dir) + "/",
                     "--format", "excellon",
                     "--generate-map", "--map-format", "gerberx2",
                     str(pcb_path)]
        subprocess.run(drill_cmd, capture_output=True, text=True, timeout=60)

        # Collect what was actually generated
        exported = []
        gerber_path = Path(gerber_dir)
        for f in sorted(gerber_path.iterdir()):
            if f.is_file():
                exported.append((f.name, f.name))
        return exported

    # ── Fallback: pcbnew PLOT_CONTROLLER ──────────────────────────────
    plot_ctrl = pcbnew.PLOT_CONTROLLER(board)
    plot_opts = plot_ctrl.GetPlotOptions()

    plot_opts.SetOutputDirectory(str(gerber_dir))
    plot_opts.SetPlotFrameRef(False)
    plot_opts.SetAutoScale(False)
    plot_opts.SetScale(1.0)
    plot_opts.SetMirror(False)
    plot_opts.SetNegative(False)
    plot_opts.SetFormat(pcbnew.PLOT_FORMAT_GERBER)
    plot_opts.SetGerberPrecision(6)
    plot_opts.SetCreateGerberJobFile(False)
    plot_opts.SetIncludeGerberNetlistInfo(True)
    plot_opts.SetSubtractMaskFromSilk(True)
    plot_opts.SetDrillMarksType(pcbnew.DRILL_MARKS_NO_DRILL_SHAPE)
    plot_opts.SetPlotReference(True)
    plot_opts.SetPlotValue(True)

    exported = []

    for layer_id, ext, desc in GERBER_LAYERS:
        filename = f"board.{ext}"
        plot_ctrl.OpenPlotfile(filename, pcbnew.PLOT_FORMAT_GERBER, desc)
        plot_ctrl.SetLayer(layer_id)
        plot_ctrl.PlotLayer()
        plot_ctrl.ClosePlot()
        # Verify file was actually created
        if Path(gerber_dir, filename).exists():
            exported.append((filename, desc))
        else:
            print(f"[postprocess] WARNING: {filename} was not generated")

    if layer_count > 2:
        inner_needed = min(layer_count - 2, len(INNER_LAYERS))
        for i in range(inner_needed):
            layer_id, ext, desc = INNER_LAYERS[i]
            filename = f"board.{ext}"
            plot_ctrl.OpenPlotfile(filename, pcbnew.PLOT_FORMAT_GERBER, desc)
            plot_ctrl.SetLayer(layer_id)
            plot_ctrl.PlotLayer()
            plot_ctrl.ClosePlot()
            if Path(gerber_dir, filename).exists():
                exported.append((filename, desc))
            else:
                print(f"[postprocess] WARNING: {filename} was not generated")

    return exported


# ─── Drill export ─────────────────────────────────────────────────────────────

def export_drill(board, gerber_dir):
    """Export Excellon drill file."""
    drill_writer = pcbnew.EXCELLON_WRITER(board)
    drill_writer.SetOptions(
        False,  # aMirror
        True,   # aMinimalHeader
        board.GetDesignSettings().GetAuxOrigin(),  # aOffset
        False,  # aMerge_PTH_NPTH
    )
    drill_writer.SetFormat(True)  # metric
    drill_writer.CreateDrillandMapFilesSet(str(gerber_dir), True, False)


# ─── BOM CSV ──────────────────────────────────────────────────────────────────

def generate_bom(placement, db, out_path):
    """Generate BOM CSV from placement data + component database."""
    components = placement.get("components", [])
    rows = []

    for comp in components:
        ref = comp.get("ref", "")
        cid = comp.get("component_id", "")
        entry = db.get(cid, {})

        rows.append({
            "Ref":        ref,
            "Value":      entry.get("display_name", cid),
            "MPN":        entry.get("mpn", ""),
            "Package":    entry.get("kicad_footprint", ""),
            "DigiKey_PN": entry.get("digikey_pn", ""),
            "LCSC_PN":    entry.get("lcsc_pn", ""),
            "Unit_Cost":  entry.get("cost_gbp_unit", ""),
            "Category":   entry.get("category", ""),
        })

    # Sort by ref designator
    rows.sort(key=lambda r: r["Ref"])

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Ref", "Value", "MPN", "Package", "DigiKey_PN", "LCSC_PN",
            "Unit_Cost", "Category",
        ])
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


# ─── Pick and place CSV ───────────────────────────────────────────────────────

def generate_pnp(placement, db, out_path):
    """Generate pick-and-place CSV from placement data."""
    components = placement.get("components", [])
    rows = []

    for comp in components:
        ref    = comp.get("ref", "")
        cid    = comp.get("component_id", "")
        entry  = db.get(cid, {})

        rows.append({
            "Ref":     ref,
            "Val":     entry.get("mpn", entry.get("display_name", cid)),
            "Package": entry.get("kicad_footprint", ""),
            "PosX":    f"{comp.get('x_mm', 0):.2f}",
            "PosY":    f"{comp.get('y_mm', 0):.2f}",
            "Rot":     f"{comp.get('rotation_deg', 0):.2f}",
            "Side":    "top",
        })

    rows.sort(key=lambda r: r["Ref"])

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Ref", "Val", "Package", "PosX", "PosY", "Rot", "Side",
        ])
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


# ─── DRC failure text ─────────────────────────────────────────────────────────

def generate_drc_text(drc_report, out_path):
    """Write a plain-English DRC failure summary if errors exist."""
    if not drc_report or drc_report.get("clean", True):
        return False

    lines = ["EISLA DESIGN RULE CHECK REPORT", "=" * 40, ""]

    errors   = drc_report.get("errors", [])
    warnings = drc_report.get("warnings", [])
    unrouted = drc_report.get("unrouted_count", 0)

    if errors:
        lines.append(f"ERRORS ({len(errors)}):")
        for e in errors:
            loc = f" at {e.get('location', '')}" if e.get("location") else ""
            msg = e.get("description", e.get("message", "unknown"))
            lines.append(f"  - {e.get('type', 'error')}: {msg}{loc}")
        lines.append("")

    if unrouted:
        lines.append(f"UNROUTED CONNECTIONS: {unrouted}")
        lines.append("  Some nets could not be routed automatically.")
        lines.append("  These may need manual routing or design adjustment.")
        lines.append("")

    if warnings:
        lines.append(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            loc = f" at {w.get('location', '')}" if w.get("location") else ""
            msg = w.get("description", w.get("message", "unknown"))
            lines.append(f"  - {w.get('type', 'warning')}: {msg}{loc}")
        lines.append("")

    lines.append("These results are included for reference.")
    lines.append("DRC errors do not block delivery of design files.")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return True


# ─── Validation warnings text ─────────────────────────────────────────────────

def generate_validation_text(warnings_data, out_path):
    """Write plain-English validation warnings if any exist."""
    if not warnings_data:
        return False

    warns = warnings_data.get("warnings", [])
    auto  = warnings_data.get("auto_resolved", [])

    if not warns and not auto:
        return False

    lines = ["EISLA DESIGN VALIDATION REPORT", "=" * 40, ""]

    if warns:
        lines.append(f"WARNINGS ({len(warns)}):")
        for w in warns:
            lines.append(f"  [{w.get('severity','warning').upper()}] {w.get('check','')}")
            lines.append(f"    {w.get('message','')}")
        lines.append("")

    if auto:
        lines.append(f"AUTO-RESOLVED ({len(auto)}):")
        for a in auto:
            lines.append(f"  {a.get('check','')}: {a.get('message','')}")
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return True


# ─── ZIP packaging ────────────────────────────────────────────────────────────

def package_zip(job_dir, gerber_dir):
    """Create output.zip with all deliverable files."""
    zip_path = job_dir / "output.zip"

    # Files to include (path relative to job_dir, name in zip)
    files = []

    # KiCad files
    for name in ["board.kicad_pcb", "board.kicad_sch", "board.kicad_pro"]:
        p = job_dir / name
        if p.exists():
            files.append((p, name))

    # CSVs and reports
    for name in ["bom.csv", "pick_and_place.csv", "drc_report.json",
                  "DRC_FAILED.txt", "validation_warnings.txt"]:
        p = job_dir / name
        if p.exists():
            files.append((p, name))

    # Gerber files
    gerber_path = Path(gerber_dir)
    if gerber_path.exists():
        for gfile in sorted(gerber_path.iterdir()):
            if gfile.is_file():
                files.append((gfile, f"gerbers/{gfile.name}"))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath, arcname in files:
            zf.write(filepath, arcname)

    size_kb = zip_path.stat().st_size // 1024
    return zip_path, len(files), size_kb


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python postprocess.py <job_dir>")
        sys.exit(1)

    job_dir    = Path(sys.argv[1])
    gerber_dir = job_dir / "gerbers"
    pcb_path   = job_dir / "board.kicad_pcb"

    if not pcb_path.exists():
        print(f"ERROR: board.kicad_pcb not found in {job_dir}")
        sys.exit(1)

    db         = load_db()
    placement  = load_json(job_dir / "placement.json")
    drc_report = load_json(job_dir / "drc_report.json")
    warnings   = load_json(job_dir / "validation_warnings.json")
    board_data = load_json(job_dir / "board.json")

    if not placement:
        print(f"ERROR: placement.json not found in {job_dir}")
        sys.exit(1)

    # Determine layer count (4-layer minimum per BRIEF.md)
    layer_count = 4
    if board_data:
        layer_count = max(board_data.get("layers", 4), 4)

    # ── 1. Load board ─────────────────────────────────────────────────────
    print(f"[postprocess] Loading board ...")
    board = pcbnew.LoadBoard(str(pcb_path))

    # ── 2. Export Gerbers ─────────────────────────────────────────────────
    print(f"[postprocess] Exporting Gerbers ({layer_count} layers) ...")
    exported = export_gerbers(board, str(gerber_dir), layer_count, pcb_path=str(pcb_path))
    for name, desc in exported:
        print(f"  {name} ({desc})")

    # ── 3. Export drill ───────────────────────────────────────────────────
    # Fallback drill export if kicad-cli was not used
    if not list(Path(gerber_dir).glob("*.drl")):
        print(f"[postprocess] Exporting drill file (fallback) ...")
        export_drill(board, str(gerber_dir))

    # ── 4. BOM ────────────────────────────────────────────────────────────
    bom_count = generate_bom(placement, db, job_dir / "bom.csv")
    print(f"[postprocess] BOM: {bom_count} components")

    # ── 5. Pick & Place ───────────────────────────────────────────────────
    pnp_count = generate_pnp(placement, db, job_dir / "pick_and_place.csv")
    print(f"[postprocess] Pick & Place: {pnp_count} placements")

    # ── 6. DRC failure text ───────────────────────────────────────────────
    if generate_drc_text(drc_report, job_dir / "DRC_FAILED.txt"):
        e = drc_report.get("error_count", 0)
        u = drc_report.get("unrouted_count", 0)
        print(f"[postprocess] DRC_FAILED.txt written ({e} errors, {u} unrouted)")

    # ── 7. Validation warnings text ───────────────────────────────────────
    if generate_validation_text(warnings, job_dir / "validation_warnings.txt"):
        print(f"[postprocess] validation_warnings.txt written")

    # ── 8. ZIP ────────────────────────────────────────────────────────────
    print(f"[postprocess] Packaging output.zip ...")
    zip_path, file_count, size_kb = package_zip(job_dir, gerber_dir)
    print(f"[postprocess] output.zip: {file_count} files, {size_kb} KB")
    print(f"[postprocess] Done")


if __name__ == "__main__":
    main()
