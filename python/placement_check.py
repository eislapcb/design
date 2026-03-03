"""
Eisla -- Post-Placement Validation (python/placement_check.py)

Runs after placement.py, before kicad_pcb.py.

Reads placement.json + components.json + netlist.json and checks placement
quality against industry best practices. All checks emit warnings (not hard
failures) — the pipeline continues regardless.

Output: placement_warnings.json

Usage:
    python placement_check.py <job_dir>
"""

import json
import math
import sys
from pathlib import Path

SCRIPT_DIR      = Path(__file__).parent
PROJECT_ROOT    = SCRIPT_DIR.parent
COMPONENTS_PATH = PROJECT_ROOT / "data" / "components.json"


def load_json(path):
    if not Path(path).exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── Geometry helpers ────────────────────────────────────────────────────────

def _centroid(comp, db=None):
    """Return (x, y) courtyard centre of a placed component.
    Accounts for footprint_center_offset_mm (e.g. ESP32-WROOM-32
    where footprint origin != courtyard centre)."""
    x = comp.get("x_mm", 0.0)
    y = comp.get("y_mm", 0.0)
    if db:
        cid = comp.get("component_id", "")
        db_entry = db.get(cid, {})
        offset = db_entry.get("footprint_center_offset_mm")
        if offset:
            rot = comp.get("rotation_deg", 0)
            rad = math.radians(rot)
            ox, oy = offset.get("x", 0), offset.get("y", 0)
            x += ox * math.cos(rad) - oy * math.sin(rad)
            y += ox * math.sin(rad) + oy * math.cos(rad)
    return x, y


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _effective_dims(comp):
    """Return (w, h) accounting for 90/270 rotation."""
    w = comp.get("width_mm", 0)
    h = comp.get("height_mm", 0)
    rot = comp.get("rotation_deg", 0) % 360
    if rot in (90, 270):
        return h, w
    return w, h


# ─── Checks ──────────────────────────────────────────────────────────────────

def check_decoupling_proximity(components, db):
    """Decoupling caps should be ≤3mm from their parent IC (≤5mm for bulk)."""
    warnings = []

    # Build ref → component lookup
    ref_map = {c["ref"]: c for c in components}

    for comp in components:
        cid = comp.get("component_id", "")
        db_entry = db.get(cid, {})
        role = db_entry.get("generic_role", "")

        if "decoupling" not in role:
            continue

        limit = 5.0 if "bulk" in role else 3.0

        # Find parent IC: look for "for Xn" pattern in reason or display_name
        parent_ref = _find_parent_ref(comp, components, db)
        if not parent_ref or parent_ref not in ref_map:
            continue

        parent = ref_map[parent_ref]

        # Edge-to-edge AABB distance (not center-to-center) so that
        # caps next to a large module like ESP32 aren't reported as 15mm away.
        cx, cy = _centroid(comp, db)
        px, py = _centroid(parent, db)
        cw, ch = _effective_dims(comp)
        pw, ph = _effective_dims(parent)
        dx = max(0, abs(cx - px) - (cw + pw) / 2)
        dy = max(0, abs(cy - py) - (ch + ph) / 2)
        d = math.hypot(dx, dy)

        if d > limit:
            warnings.append({
                "check": "decoupling_proximity",
                "ref": comp["ref"],
                "parent": parent_ref,
                "distance_mm": round(d, 1),
                "limit_mm": limit,
                "message": f"{comp['ref']} ({cid}) is {d:.1f}mm from {parent_ref} (limit: {limit}mm)",
            })

    return warnings


def check_crystal_proximity(components, db):
    """Crystals should be ≤5mm from MCU."""
    warnings = []

    mcu = None
    crystals = []
    for comp in components:
        cid = comp.get("component_id", "")
        db_entry = db.get(cid, {})
        if db_entry.get("category") == "mcu":
            mcu = comp
        if "crystal" in cid.lower() or db_entry.get("generic_role", "") == "crystal_load":
            crystals.append(comp)

    if not mcu or not crystals:
        return warnings

    for crystal in crystals:
        d = _dist(_centroid(crystal, db), _centroid(mcu, db))
        if d > 5.0:
            warnings.append({
                "check": "crystal_proximity",
                "ref": crystal["ref"],
                "mcu": mcu["ref"],
                "distance_mm": round(d, 1),
                "limit_mm": 5.0,
                "message": f"{crystal['ref']} is {d:.1f}mm from MCU {mcu['ref']} (limit: 5mm)",
            })

    return warnings


def check_connector_edges(components, db, board_w, board_h):
    """Edge-zone connectors should be within 1mm of the board edge."""
    warnings = []
    edge_zones = {"edge_top", "edge_bottom", "edge_left", "edge_right"}

    for comp in components:
        zone = comp.get("placement_zone", "")
        if zone not in edge_zones:
            continue

        x, y = _centroid(comp, db)
        w, h = _effective_dims(comp)

        if zone == "edge_top":
            edge_dist = y - h / 2
        elif zone == "edge_bottom":
            edge_dist = board_h - (y + h / 2)
        elif zone == "edge_left":
            edge_dist = x - w / 2
        elif zone == "edge_right":
            edge_dist = board_w - (x + w / 2)
        else:
            continue

        if edge_dist > 1.0:
            warnings.append({
                "check": "connector_edge_alignment",
                "ref": comp["ref"],
                "zone": zone,
                "edge_distance_mm": round(edge_dist, 1),
                "limit_mm": 1.0,
                "message": f"{comp['ref']} is {edge_dist:.1f}mm from {zone} edge (limit: 1mm)",
            })

    return warnings


def check_spacing(components, db):
    """All component pairs should have ≥0.5mm courtyard gap."""
    warnings = []
    MIN_GAP = 0.5

    for i, a in enumerate(components):
        ax, ay = _centroid(a, db)
        aw, ah = _effective_dims(a)
        for b in components[i + 1:]:
            bx, by = _centroid(b, db)
            bw, bh = _effective_dims(b)

            # AABB overlap check with gap
            gap_x = abs(ax - bx) - (aw + bw) / 2
            gap_y = abs(ay - by) - (ah + bh) / 2

            if gap_x < MIN_GAP and gap_y < MIN_GAP:
                gap = max(gap_x, gap_y)
                if gap < MIN_GAP:
                    warnings.append({
                        "check": "component_spacing",
                        "ref_a": a["ref"],
                        "ref_b": b["ref"],
                        "gap_mm": round(gap, 2),
                        "limit_mm": MIN_GAP,
                        "message": f"{a['ref']} and {b['ref']} are {gap:.2f}mm apart (min: {MIN_GAP}mm)",
                    })

    return warnings


# ─── Parent ref finder ───────────────────────────────────────────────────────

def _find_parent_ref(comp, components, db):
    """Find the parent IC ref for an auto-added passive (decoupling cap, etc.)."""
    # Check display_name for "for Xn" pattern (e.g. "100nF decoupling for U1")
    display = comp.get("display_name", "")
    for c in components:
        ref = c.get("ref", "")
        if ref and f"for {ref}" in display:
            return ref

    # Fallback: find the nearest IC (MCU preferred)
    cid = comp.get("component_id", "")
    pos = _centroid(comp, db)
    best_ref = None
    best_dist = float("inf")
    for c in components:
        c_db = db.get(c.get("component_id", ""), {})
        cat = c_db.get("category", "")
        if cat not in ("mcu", "power", "comms", "sensor", "motor_driver", "connector"):
            continue
        d = _dist(pos, _centroid(c, db))
        # Prefer MCU
        if cat == "mcu":
            d *= 0.5
        if d < best_dist:
            best_dist = d
            best_ref = c["ref"]

    return best_ref


# ─── Main ────────────────────────────────────────────────────────────────────

def check_placement(job_dir):
    """Run all placement checks and write placement_warnings.json."""
    job_dir = Path(job_dir)
    db = load_json(COMPONENTS_PATH) or {}
    placement = load_json(job_dir / "placement.json")

    if not placement:
        print(f"ERROR: placement.json not found in {job_dir}")
        return []

    components = placement.get("components", [])
    board = placement.get("board", {})
    board_w = board.get("w_mm", 100.0)
    board_h = board.get("h_mm", 80.0)

    warnings = []
    warnings += check_decoupling_proximity(components, db)
    warnings += check_crystal_proximity(components, db)
    warnings += check_connector_edges(components, db, board_w, board_h)
    warnings += check_spacing(components, db)

    result = {
        "warning_count": len(warnings),
        "warnings": warnings,
        "clean": len(warnings) == 0,
    }

    out_path = job_dir / "placement_warnings.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    if warnings:
        print(f"[placement_check] {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  {w['message']}")
    else:
        print("[placement_check] All checks passed")
    print(f"[placement_check] Saved to {out_path}")

    return warnings


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python placement_check.py <job_dir>")
        sys.exit(1)
    check_placement(sys.argv[1])
