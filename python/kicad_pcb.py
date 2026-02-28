"""
Eisla -- KiCad PCB Generator (python/kicad_pcb.py)

Session 10. Runs after netlist.py.

Uses the pcbnew Python API (KiCad 9.0) to generate a placed, unrouted
board.kicad_pcb file ready for Specctra DSN export and FreeRouting.

Pipeline:
  placement.json + netlist.json -> board.kicad_pcb

MUST be run with KiCad's Python interpreter:
  "C:/Program Files/KiCad/9.0/bin/python.exe" kicad_pcb.py <job_dir>

Footprint handling:
  - Loads from KiCad standard libraries (installed with KiCad 9.0)
  - Missing footprint -> uses generic fallback + flags for engineer review
  - engineer_review_flags.json written to job_dir (merged with netlist.json flags)

Output (in job_dir):
  board.kicad_pcb         -- placed, unrouted PCB
  board.kicad_pro         -- minimal project file
  engineer_review_flags.json -- components needing manual footprint assignment
"""

import json
import sys
import os
from pathlib import Path

import pcbnew

SCRIPT_DIR      = Path(__file__).parent
PROJECT_ROOT    = SCRIPT_DIR.parent
COMPONENTS_PATH = PROJECT_ROOT / "data" / "components.json"

FP_LIB_BASE   = Path("C:/Program Files/KiCad/9.0/share/kicad/footprints")
GENERIC_FP_ID = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"  # safe fallback


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_json(path):
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_db():
    with open(COMPONENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


# ─── Footprint loading ────────────────────────────────────────────────────────

_fp_cache = {}

def load_footprint(fp_id):
    """
    Load a KiCad footprint by 'Library:Name' ID.
    Returns (footprint, ok) where ok=False means fallback was used.
    """
    if fp_id in _fp_cache:
        return _fp_cache[fp_id]

    lib_name, fp_name = fp_id.split(":", 1)
    lib_path = str(FP_LIB_BASE / f"{lib_name}.pretty")

    try:
        fp = pcbnew.FootprintLoad(lib_path, fp_name)
        if fp:
            _fp_cache[fp_id] = (fp, True)
            return fp, True
    except Exception:
        pass

    # Fallback to generic
    try:
        lib_name2, fp_name2 = GENERIC_FP_ID.split(":", 1)
        lib_path2 = str(FP_LIB_BASE / f"{lib_name2}.pretty")
        fp = pcbnew.FootprintLoad(lib_path2, fp_name2)
        if fp:
            _fp_cache[fp_id] = (fp, False)
            return fp, False
    except Exception:
        pass

    return None, False


# ─── Net helpers ──────────────────────────────────────────────────────────────

def assign_pad_nets(footprint, ref, nets_by_ref):
    """
    Assign nets to pads based on netlist data for this ref.
    nets_by_ref: {net_name: [{ref, pad}, ...]}
    """
    # Build pad-number → net-name lookup from netlist
    pad_to_net = {}
    for net_name, members in nets_by_ref.items():
        for m in members:
            if m["ref"] == ref:
                pad_to_net[str(m["pad"])] = net_name

    for pad in footprint.Pads():
        pad_num = pad.GetNumber()
        net_name = pad_to_net.get(str(pad_num))
        if net_name:
            pad.SetNet(footprint.GetBoard().FindNet(net_name))


# ─── Board builder ────────────────────────────────────────────────────────────

def build_board(placement, netlist, db):
    """
    Create and return a pcbnew BOARD.
    Returns (board, engineer_review_flags).
    """
    board = pcbnew.CreateEmptyBoard()

    board_info = placement.get("board", {})
    w_mm = board_info.get("w_mm", 100.0)
    h_mm = board_info.get("h_mm",  80.0)

    # ── Board outline (Edge.Cuts) ──────────────────────────────────────────
    edge_layer = pcbnew.Edge_Cuts
    corners = [
        (0, 0), (w_mm, 0), (w_mm, h_mm), (0, h_mm), (0, 0)
    ]
    for i in range(len(corners) - 1):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(edge_layer)
        seg.SetStart(pcbnew.FromMM(corners[i][0]), pcbnew.FromMM(corners[i][1]))
        seg.SetEnd(pcbnew.FromMM(corners[i + 1][0]), pcbnew.FromMM(corners[i + 1][1]))
        seg.SetWidth(pcbnew.FromMM(0.05))
        board.Add(seg)

    # ── Board design settings ──────────────────────────────────────────────
    ds = board.GetDesignSettings()
    ds.SetDefaultMicViaDrill(pcbnew.FromMM(0.2))
    ds.SetMinTrackWidth(pcbnew.FromMM(0.15))
    ds.SetMinClearance(pcbnew.FromMM(0.15))

    # ── Net registration ───────────────────────────────────────────────────
    nets_dict = netlist.get("nets", {})
    netinfo = board.GetNetInfo()
    net_objects = {}  # net_name -> NETINFO_ITEM

    for net_name in sorted(nets_dict.keys()):
        ni = pcbnew.NETINFO_ITEM(board, net_name)
        netinfo.AppendNet(ni)
        net_objects[net_name] = ni

    # ── Place footprints ───────────────────────────────────────────────────
    engineer_review = list(netlist.get("engineer_review", []))
    er_refs = {e["ref"] for e in engineer_review}

    for comp_data in placement.get("components", []):
        ref         = comp_data.get("ref", "?")
        cid         = comp_data.get("component_id", "")
        x_mm        = comp_data.get("x_mm",  0.0)
        y_mm        = comp_data.get("y_mm",  0.0)
        rot_deg     = comp_data.get("rotation_deg", 0)
        comp        = db.get(cid, {})
        fp_id       = comp.get("kicad_footprint", "")
        display     = comp.get("display_name", cid)

        if not fp_id:
            if ref not in er_refs:
                engineer_review.append({
                    "ref":          ref,
                    "component_id": cid,
                    "display_name": display,
                    "reasons":      ["kicad_footprint missing from component database"],
                })
            fp_id = GENERIC_FP_ID

        fp, fp_ok = load_footprint(fp_id)

        if fp is None:
            print(f"[kicad_pcb] WARNING: Could not load any footprint for {ref} ({fp_id}), skipping")
            continue

        if not fp_ok and ref not in er_refs:
            engineer_review.append({
                "ref":          ref,
                "component_id": cid,
                "display_name": display,
                "reasons":      [f"footprint '{fp_id}' not found — generic fallback used"],
            })

        # Clone the footprint (pcbnew reuses the same object from FootprintLoad)
        fp_clone = pcbnew.FOOTPRINT(fp)
        fp_clone.SetReference(ref)
        fp_clone.SetValue(comp.get("mpn", display))

        # Position
        fp_clone.SetPosition(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_mm),
            pcbnew.FromMM(y_mm),
        ))
        # Rotation (KiCad uses tenths of degrees in legacy API; EDA_ANGLE in v7+)
        try:
            fp_clone.SetOrientationDegrees(rot_deg)
        except AttributeError:
            fp_clone.SetOrientation(rot_deg * 10)

        board.Add(fp_clone)

        # Assign nets to pads
        assign_pad_nets(fp_clone, ref, nets_dict)

    return board, engineer_review


# ─── Project file ─────────────────────────────────────────────────────────────

def write_project_file(job_dir, board_name="board"):
    """Write a minimal .kicad_pro so KiCad opens the project correctly."""
    pro = {
        "board": {"design_settings": {}, "ibl_settings": {}},
        "libraries": {},
        "meta": {"filename": f"{board_name}.kicad_pro", "version": 1},
        "net_settings": {"classes": [{"name": "Default", "wire_width": 6}]},
        "schematic": {},
        "sheets": [],
        "text_variables": {},
    }
    out = job_dir / f"{board_name}.kicad_pro"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(pro, f, indent=2)
    return out


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python kicad_pcb.py <job_dir>")
        sys.exit(1)

    job_dir = Path(sys.argv[1])
    db        = load_db()
    placement = load_json(job_dir / "placement.json")
    netlist   = load_json(job_dir / "netlist.json")

    if not placement:
        print(f"ERROR: placement.json not found in {job_dir}")
        sys.exit(1)
    if not netlist:
        print(f"ERROR: netlist.json not found in {job_dir}")
        sys.exit(1)

    print(f"[kicad_pcb] Building board "
          f"{placement['board']['w_mm']}x{placement['board']['h_mm']}mm ...")

    board, er_flags = build_board(placement, netlist, db)

    # Save PCB
    pcb_path = str(job_dir / "board.kicad_pcb")
    pcbnew.SaveBoard(pcb_path, board)
    print(f"[kicad_pcb] Saved board.kicad_pcb ({len(placement.get('components',[]))} footprints)")

    # Save project file
    pro_path = write_project_file(job_dir)
    print(f"[kicad_pcb] Saved {pro_path.name}")

    # Write / merge engineer review flags
    er_path = job_dir / "engineer_review_flags.json"
    existing = load_json(er_path) or []
    existing_refs = {e["ref"] for e in existing}
    merged = existing + [e for e in er_flags if e["ref"] not in existing_refs]
    with open(er_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    if er_flags:
        print(f"[kicad_pcb] {len(er_flags)} component(s) flagged for engineer review:")
        for flag in er_flags:
            print(f"  {flag['ref']} ({flag['display_name']}): {'; '.join(flag['reasons'])}")
    else:
        print("[kicad_pcb] All footprints resolved from standard KiCad libraries")

    print(f"[kicad_pcb] Done")


if __name__ == "__main__":
    main()
