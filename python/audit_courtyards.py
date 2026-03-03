#!/usr/bin/env python3
"""
Courtyard Audit — compare component DB dimensions against real KiCad
footprint courtyard bounding boxes, with optional auto-fix.

Must be run with KiCad Python:
  "C:/Program Files/KiCad/9.0/bin/python.exe" python/audit_courtyards.py          # audit only
  "C:/Program Files/KiCad/9.0/bin/python.exe" python/audit_courtyards.py --fix     # audit + fix

Flags:
  - SA dimension vs courtyard mismatch (>threshold)
  - Missing footprint_center_offset_mm for off-center origins
  - Footprints that fail to load from KiCad library
"""

import json, sys
from pathlib import Path

# ── KiCad pcbnew import ──────────────────────────────────────────────────────
try:
    import pcbnew
except ImportError:
    print("ERROR: pcbnew not found. Run with KiCad Python:")
    print('  "C:/Program Files/KiCad/9.0/bin/python.exe" python/audit_courtyards.py')
    sys.exit(1)

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR     = PROJECT_ROOT / "data"
COMPONENTS_PATH = DATA_DIR / "components.json"
FP_LIB_BASE  = Path("C:/Program Files/KiCad/9.0/share/kicad/footprints")
FP_LIB_LOCAL = DATA_DIR / "footprints"   # custom Eisla footprints

# Thresholds (mm)
DIM_MISMATCH_THRESHOLD = 0.5
OFFSET_THRESHOLD       = 0.5


def load_components():
    with open(COMPONENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_components(db):
    with open(COMPONENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_courtyard_bbox(fp):
    """Extract F.CrtYd bounding box from a loaded footprint.
    Returns (width_mm, height_mm, cx_mm, cy_mm) where cx/cy is the
    courtyard center relative to the footprint origin (anchor)."""
    drawings = fp.GraphicalItems()
    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")
    found = False

    for item in drawings:
        if item.GetLayer() != pcbnew.F_CrtYd:
            continue
        bbox = item.GetBoundingBox()
        x1 = pcbnew.ToMM(bbox.GetLeft())
        y1 = pcbnew.ToMM(bbox.GetTop())
        x2 = pcbnew.ToMM(bbox.GetRight())
        y2 = pcbnew.ToMM(bbox.GetBottom())
        min_x = min(min_x, x1)
        max_x = max(max_x, x2)
        min_y = min(min_y, y1)
        max_y = max(max_y, y2)
        found = True

    if not found:
        return None

    w = round(max_x - min_x, 3)
    h = round(max_y - min_y, 3)
    cx = round((min_x + max_x) / 2, 3)
    cy = round((min_y + max_y) / 2, 3)
    return w, h, cx, cy


def get_sa_dims(comp):
    """Get the SA-used dimensions for a component (same logic as placement.py).
    Returns (sa_width, sa_height) which = dimensions_mm + 2*clearance."""
    dims = comp.get("dimensions_mm", {})
    clearance = comp.get("courtyard_clearance_mm", 0.5)
    w = dims.get("width", 5.0)
    h = dims.get("length", dims.get("height", 5.0))
    return w + clearance * 2, h + clearance * 2


def load_footprint(fp_id):
    """Load a KiCad footprint by 'Library:Name' ID.
    Searches local Eisla library first, then standard KiCad."""
    lib_name, fp_name = fp_id.split(":", 1)
    for lib_base in (FP_LIB_LOCAL, FP_LIB_BASE):
        lib_path = str(lib_base / f"{lib_name}.pretty")
        try:
            fp = pcbnew.FootprintLoad(lib_path, fp_name)
            if fp:
                return fp
        except Exception:
            pass
    return None


def audit(fix=False):
    db = load_components()
    issues = []
    fixes_applied = 0
    ok_count = 0
    fail_count = 0
    skip_count = 0

    print(f"Auditing {len(db)} components...{' (fix mode)' if fix else ''}\n")

    for cid, comp in sorted(db.items()):
        fp_id = comp.get("kicad_footprint")
        if not fp_id:
            skip_count += 1
            continue

        fp = load_footprint(fp_id)
        if fp is None:
            issues.append({
                "component": cid,
                "footprint": fp_id,
                "type": "load_failed",
                "message": "Footprint failed to load from KiCad library",
            })
            fail_count += 1
            continue

        bbox = get_courtyard_bbox(fp)
        if bbox is None:
            issues.append({
                "component": cid,
                "footprint": fp_id,
                "type": "no_courtyard",
                "message": "No F.CrtYd layer found on footprint",
            })
            fail_count += 1
            continue

        kicad_w, kicad_h, cx, cy = bbox
        sa_w, sa_h = get_sa_dims(comp)
        clearance = comp.get("courtyard_clearance_mm", 0.5)

        # Compare dimensions (handle rotation: try both orientations)
        dw = abs(sa_w - kicad_w)
        dh = abs(sa_h - kicad_h)
        dw_rot = abs(sa_w - kicad_h)
        dh_rot = abs(sa_h - kicad_w)

        if max(dw, dh) <= max(dw_rot, dh_rot):
            delta_w, delta_h = dw, dh
            rotated = False
        else:
            delta_w, delta_h = dw_rot, dh_rot
            rotated = True

        has_dim_issue = delta_w > DIM_MISMATCH_THRESHOLD or delta_h > DIM_MISMATCH_THRESHOLD

        if has_dim_issue:
            # Compute recommended dimensions_mm values:
            # SA will compute: dimensions_mm.width + 2*clearance
            # We want that to equal kicad_courtyard_width
            # So: dimensions_mm.width = kicad_w - 2*clearance
            rec_w = round(kicad_w - clearance * 2, 2)
            rec_h = round(kicad_h - clearance * 2, 2)

            issues.append({
                "component": cid,
                "footprint": fp_id,
                "type": "dimension_mismatch",
                "sa_dims": f"{sa_w:.2f} x {sa_h:.2f}",
                "kicad_courtyard": f"{kicad_w:.2f} x {kicad_h:.2f}",
                "delta_w": round(delta_w, 2),
                "delta_h": round(delta_h, 2),
                "recommended": f"{rec_w:.2f} x {rec_h:.2f}",
                "message": f"SA {sa_w:.2f}x{sa_h:.2f} vs KiCad {kicad_w:.2f}x{kicad_h:.2f} "
                           f"→ rec: {rec_w:.2f}x{rec_h:.2f}",
            })

            if fix:
                dims = comp.get("dimensions_mm", {})
                dims["width"] = rec_w
                # Preserve 'length' key if it existed, otherwise use 'height'
                if "length" in dims:
                    dims["length"] = rec_h
                else:
                    dims["height"] = rec_h
                comp["dimensions_mm"] = dims
                fixes_applied += 1

        # Check footprint center offset
        declared_offset = comp.get("footprint_center_offset_mm", {})
        declared_cx = declared_offset.get("x", 0)
        declared_cy = declared_offset.get("y", 0)
        actual_offset_x = abs(cx - declared_cx)
        actual_offset_y = abs(cy - declared_cy)

        has_offset_issue = (actual_offset_x > OFFSET_THRESHOLD or
                           actual_offset_y > OFFSET_THRESHOLD)

        if has_offset_issue:
            issues.append({
                "component": cid,
                "footprint": fp_id,
                "type": "center_offset",
                "courtyard_center": f"({cx:.2f}, {cy:.2f})",
                "declared_offset": f"({declared_cx:.2f}, {declared_cy:.2f})",
                "message": f"Courtyard center at ({cx:.2f}, {cy:.2f}) vs "
                           f"declared offset ({declared_cx:.2f}, {declared_cy:.2f})",
            })

            if fix:
                comp["footprint_center_offset_mm"] = {
                    "x": round(cx, 2),
                    "y": round(cy, 2),
                }
                fixes_applied += 1

        if not has_dim_issue and not has_offset_issue:
            ok_count += 1
        else:
            fail_count += 1

    # ── Print results ─────────────────────────────────────────────────────
    dim_issues = [i for i in issues if i["type"] == "dimension_mismatch"]
    offset_issues = [i for i in issues if i["type"] == "center_offset"]
    load_issues = [i for i in issues if i["type"] in ("load_failed", "no_courtyard")]

    if load_issues:
        print("=" * 70)
        print(f"LOAD FAILURES ({len(load_issues)})")
        print("=" * 70)
        for i in load_issues:
            print(f"  {i['component']:30s}  {i['footprint']}")
            print(f"    {i['message']}")
        print()

    if dim_issues:
        print("=" * 70)
        print(f"DIMENSION MISMATCHES ({len(dim_issues)})")
        print("=" * 70)
        dim_issues.sort(key=lambda i: max(i["delta_w"], i["delta_h"]), reverse=True)
        for i in dim_issues:
            print(f"  {i['component']:30s}  {i['footprint']}")
            print(f"    SA: {i['sa_dims']:>14s}   KiCad: {i['kicad_courtyard']:>14s}   "
                  f"rec: {i['recommended']:>14s}")
        print()

    if offset_issues:
        print("=" * 70)
        print(f"CENTER OFFSET MISMATCHES ({len(offset_issues)})")
        print("=" * 70)
        for i in offset_issues:
            print(f"  {i['component']:30s}  {i['footprint']}")
            print(f"    {i['message']}")
        print()

    print("=" * 70)
    print(f"SUMMARY: {ok_count} OK, {fail_count} issues, {skip_count} skipped"
          f"{f', {fixes_applied} fixes applied' if fix else ''}")
    print("=" * 70)

    if fix and fixes_applied > 0:
        save_components(db)
        print(f"\nUpdated {COMPONENTS_PATH}")

    # Write JSON report
    report_path = PROJECT_ROOT / "audit_courtyard_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "ok_count": ok_count,
            "issue_count": fail_count,
            "skip_count": skip_count,
            "fixes_applied": fixes_applied,
            "issues": issues,
        }, f, indent=2)
    print(f"Full report: {report_path}")

    return len(issues) == 0


if __name__ == "__main__":
    fix_mode = "--fix" in sys.argv
    ok = audit(fix=fix_mode)
    sys.exit(0 if ok else 1)
