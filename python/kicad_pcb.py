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
FP_LIB_LOCAL  = PROJECT_ROOT / "data" / "footprints"   # custom Eisla footprints
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

_fp_ok_cache = {}  # fp_id -> bool (whether the footprint loaded successfully)

def load_footprint(fp_id):
    """
    Load a KiCad footprint by 'Library:Name' ID.
    Returns (footprint, ok) where ok=False means fallback was used.

    Each call returns a FRESH footprint with unique UUIDs — required to
    prevent false courtyard-overlap DRC errors when multiple instances of
    the same footprint type are placed on the board.
    """
    lib_name, fp_name = fp_id.split(":", 1)
    lib_paths = [
        str(FP_LIB_LOCAL / f"{lib_name}.pretty"),   # local Eisla library first
        str(FP_LIB_BASE  / f"{lib_name}.pretty"),   # then standard KiCad
    ]

    # Check if we already know this fp_id fails (avoid repeated disk hits)
    if fp_id in _fp_ok_cache and _fp_ok_cache[fp_id]:
        for lib_path in lib_paths:
            try:
                fp = pcbnew.FootprintLoad(lib_path, fp_name)
                if fp:
                    return fp, True
            except Exception:
                pass

    if fp_id not in _fp_ok_cache:
        for lib_path in lib_paths:
            try:
                fp = pcbnew.FootprintLoad(lib_path, fp_name)
                if fp:
                    _fp_ok_cache[fp_id] = True
                    return fp, True
            except Exception:
                pass
        _fp_ok_cache[fp_id] = False

    # Fallback to generic
    try:
        lib_name2, fp_name2 = GENERIC_FP_ID.split(":", 1)
        lib_path2 = str(FP_LIB_BASE / f"{lib_name2}.pretty")
        fp = pcbnew.FootprintLoad(lib_path2, fp_name2)
        if fp:
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


# ─── Net class helpers ────────────────────────────────────────────────────────

def _apply_net_classes(ds, job_dir):
    """Load net_classes.json and register custom net classes via pcbnew API."""
    if not job_dir:
        return
    nc_path = Path(job_dir) / "net_classes.json"
    nc_data = load_json(nc_path)
    if not nc_data:
        return

    assignments = nc_data.get("assignments", {})
    ns = ds.m_NetSettings

    for cls_name in ("Power", "HighSpeed", "Analog"):
        params = nc_data.get(cls_name)
        if not params:
            continue
        try:
            nclass = pcbnew.NETCLASS(cls_name)
            nclass.SetClearance(pcbnew.FromMM(params["clearance"]))
            nclass.SetTrackWidth(pcbnew.FromMM(params["track_width"]))
            nclass.SetViaDiameter(pcbnew.FromMM(params["via_dia"]))
            nclass.SetViaDrill(pcbnew.FromMM(params["via_drill"]))
            ns.SetNetclass(cls_name, nclass)
        except Exception as e:
            print(f"[kicad_pcb] WARNING: Could not create netclass '{cls_name}': {e}")

    # Assign individual nets to their classes
    assigned = 0
    for net_name, cls_name in assignments.items():
        if cls_name == "Default":
            continue
        try:
            ns.SetNetclassPatternAssignment(net_name, cls_name)
            assigned += 1
        except Exception:
            # KiCad 9 may use different API — try alternate method
            try:
                ns.ResolveNetClassAssignments()
            except Exception:
                pass

    if assigned:
        print(f"[kicad_pcb] Registered {assigned} net-to-class assignments")


# ─── Board builder ────────────────────────────────────────────────────────────

def build_board(placement, netlist, db, board_spec=None, job_dir=None):
    """
    Create and return a pcbnew BOARD.
    Returns (board, engineer_review_flags).
    board_spec: optional dict from board.json (layers, power_source, etc.)
    job_dir: Path to job directory (for loading net_classes.json)
    """
    board = pcbnew.CreateEmptyBoard()

    board_info = placement.get("board", {})
    w_mm = board_info.get("w_mm", 100.0)
    h_mm = board_info.get("h_mm",  80.0)

    # ── Copper layer count from board.json ────────────────────────────────
    n_layers = (board_spec or {}).get("layers", 4)
    if n_layers not in (2, 4, 6, 8):
        n_layers = 4
    n_layers = max(n_layers, 4)  # All Eisla boards are 4-layer minimum
    board.SetCopperLayerCount(n_layers)

    # ── Board outline (Edge.Cuts) ──────────────────────────────────────────
    edge_layer = pcbnew.Edge_Cuts
    corners = [
        (0, 0), (w_mm, 0), (w_mm, h_mm), (0, h_mm), (0, 0)
    ]
    for i in range(len(corners) - 1):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(edge_layer)
        seg.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(corners[i][0]), pcbnew.FromMM(corners[i][1])))
        seg.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(corners[i + 1][0]), pcbnew.FromMM(corners[i + 1][1])))
        seg.SetWidth(pcbnew.FromMM(0.05))
        board.Add(seg)

    # ── Board design settings ──────────────────────────────────────────────
    ds = board.GetDesignSettings()
    ds.m_MicroViasMinDrill = pcbnew.FromMM(0.2)
    ds.m_TrackMinWidth = pcbnew.FromMM(0.15)
    ds.m_MinClearance = pcbnew.FromMM(0.15)
    ds.m_ViasMinSize = pcbnew.FromMM(0.5)  # 0.2mm drill + 2×0.15mm annular ring (IPC-2221B)
    ds.m_ViasMinDrill = pcbnew.FromMM(0.2)
    ds.m_MinThroughDrill = pcbnew.FromMM(0.2)
    ds.m_CopperEdgeClearance = pcbnew.FromMM(0.25)  # minimum copper-to-edge clearance

    # Set default netclass clearance + via size to match FreeRouting output
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetClearance(pcbnew.FromMM(0.15))
    nc.SetViaDiameter(pcbnew.FromMM(0.6))
    nc.SetViaDrill(pcbnew.FromMM(0.3))

    # ── Custom net classes (from net_classes.json) ────────────────────────
    _apply_net_classes(ds, job_dir)

    # ── Net registration ───────────────────────────────────────────────────
    nets_dict = netlist.get("nets", {})
    netinfo = board.GetNetInfo()
    net_objects = {}  # net_name -> NETINFO_ITEM

    for net_name in sorted(nets_dict.keys()):
        ni = pcbnew.NETINFO_ITEM(board, net_name)
        board.Add(ni)
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

        # Each load_footprint() call returns a fresh object with unique UUIDs
        fp.SetReference(ref)
        fp.SetValue(comp.get("mpn", display))

        # Position
        fp.SetPosition(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_mm),
            pcbnew.FromMM(y_mm),
        ))
        # Rotation (KiCad uses tenths of degrees in legacy API; EDA_ANGLE in v7+)
        try:
            fp.SetOrientationDegrees(rot_deg)
        except AttributeError:
            fp.SetOrientation(rot_deg * 10)

        board.Add(fp)

        # Assign nets to pads
        assign_pad_nets(fp, ref, nets_dict)

    # ── Copper zone fills ────────────────────────────────────────────────
    # Standard 4-layer stackup:
    #   F.Cu  — signals + GND pour (absorbs GND routing artifacts)
    #   In1   — dedicated GND plane
    #   In2   — dedicated power plane
    #   B.Cu  — signals + GND pour
    if n_layers >= 4:
        _add_zone_fill(board, w_mm, h_mm, net_objects, "GND", pcbnew.F_Cu, priority=1)
        _add_zone_fill(board, w_mm, h_mm, net_objects, "GND", pcbnew.In1_Cu)
        _add_zone_fill(board, w_mm, h_mm, net_objects, "GND", pcbnew.B_Cu, priority=1)
        for pwr_net in ("VCC_3V3", "VCC_5V", "VBAT"):
            if pwr_net in net_objects:
                _add_zone_fill(board, w_mm, h_mm, net_objects, pwr_net, pcbnew.In2_Cu)
                break

    return board, engineer_review


def _add_zone_fill(board, w_mm, h_mm, net_objects, net_name, layer, priority=0):
    """Add a copper zone fill covering the full board on a given layer."""
    ni = net_objects.get(net_name)
    if not ni:
        return
    zone = pcbnew.ZONE(board)
    zone.SetNet(ni)
    zone.SetLayer(layer)
    zone.SetAssignedPriority(priority)
    zone.SetMinThickness(pcbnew.FromMM(0.25))
    is_outer = layer in (pcbnew.F_Cu, pcbnew.B_Cu)
    # FULL (solid) connection on all layers.  Auto-routed traces
    # block thermal relief spokes on outer layers, causing starved-
    # thermal DRC errors and unconnected GND pads.  Solid fill
    # avoids this and is correct for reflow soldering (all Eisla
    # boards are pick-and-place + reflow, never hand-soldered).
    try:
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    except Exception:
        pass
    # Remove isolated copper islands on outer layers — auto-routing creates
    # small disconnected zone fragments that DRC flags as unconnected.
    if is_outer:
        try:
            zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        except Exception:
            pass
    # Zone outline = board perimeter with 0.1mm inset
    inset = 0.1
    outline = zone.Outline()
    outline.NewOutline()
    for cx, cy in [(inset, inset), (w_mm - inset, inset),
                   (w_mm - inset, h_mm - inset), (inset, h_mm - inset)]:
        outline.Append(pcbnew.FromMM(cx), pcbnew.FromMM(cy))
    board.Add(zone)


# ─── Project file ─────────────────────────────────────────────────────────────

def write_project_file(job_dir, board_name="board"):
    """Write a minimal .kicad_pro so KiCad opens the project correctly."""
    # Build net class list for project file
    nc_data = load_json(job_dir / "net_classes.json")
    classes = [{
        "name": "Default",
        "clearance": 0.15,
        "track_width": 0.2,
        "via_diameter": 0.6,
        "via_drill": 0.3,
        "diff_pair_gap": 0.25,
        "diff_pair_width": 0.2,
        "wire_width": 6,
    }]
    if nc_data:
        for cls_name in ("Power", "HighSpeed", "Analog"):
            params = nc_data.get(cls_name)
            if params:
                classes.append({
                    "name": cls_name,
                    "clearance": params["clearance"],
                    "track_width": params["track_width"],
                    "via_diameter": params["via_dia"],
                    "via_drill": params["via_drill"],
                    "wire_width": 6,
                })

    pro = {
        "board": {
            "design_settings": {
                "defaults": {
                    "copper_line_width": 0.2,
                    "copper_text_size_h": 1.5,
                    "copper_text_size_v": 1.5,
                },
                "rules": {
                    "min_clearance": 0.15,
                    "min_track_width": 0.15,
                    "min_via_diameter": 0.5,
                    "min_via_annular_width": 0.15,
                    "min_through_hole_diameter": 0.2,
                    "min_microvia_diameter": 0.2,
                    "min_microvia_drill": 0.1,
                    "min_copper_edge_clearance": 0.25,
                    "min_hole_clearance": 0.15,
                },
                "net_settings": {
                    "classes": classes,
                },
            },
            "ibl_settings": {},
        },
        "libraries": {},
        "meta": {"filename": f"{board_name}.kicad_pro", "version": 1},
        "net_settings": {
            "classes": classes,
        },
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
    board_spec = load_json(job_dir / "board.json") or {}

    if not placement:
        print(f"ERROR: placement.json not found in {job_dir}")
        sys.exit(1)
    if not netlist:
        print(f"ERROR: netlist.json not found in {job_dir}")
        sys.exit(1)

    n_layers = board_spec.get("layers", 2)
    print(f"[kicad_pcb] Building board "
          f"{placement['board']['w_mm']}x{placement['board']['h_mm']}mm "
          f"({n_layers} copper layers) ...")

    board, er_flags = build_board(placement, netlist, db, board_spec, job_dir=job_dir)

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
