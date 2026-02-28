"""
Eisla -- SVG Placement Preview (python/svg_preview.py)

Session 9. Runs after placement.py.

Renders placement.json as an SVG board preview:
  - Board outline (2px black rectangle)
  - Components as colour-coded rectangles with ref designator labels
  - Ratsnest lines (thin grey, star topology from MCU centroid)
  - Validation warning glow (orange border) on affected components
  - Accepts --overrides flag to apply placement_overrides.json

Scale: 10 px per mm.

Usage:
    python svg_preview.py <job_dir>
    python svg_preview.py <job_dir> --overrides

Input files (in job_dir):
    placement.json           -- placement engine output
    validation_warnings.json -- optional, for warning glow
    placement_overrides.json -- optional, applied when --overrides flag set

Output (in job_dir):
    placement_preview.svg
"""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

# ─── Constants ────────────────────────────────────────────────────────────────

PX_PER_MM   = 10
MARGIN_PX   = 20          # canvas border around board
BOARD_STROKE = 2          # px, board outline
COMP_STROKE  = 1          # px, component outline
WARN_STROKE  = 3          # px, warning glow
RATSNEST_STROKE = 0.5     # px, ratsnest lines
LABEL_FONT_SIZE = 7       # px
WARN_COLOUR  = "#FF8C00"  # dark orange glow

# Category fill colours (semi-transparent)
CATEGORY_FILL = {
    "mcu":          "#4F8EF7",   # blue
    "power":        "#F7A84F",   # orange
    "sensor":       "#6BCB77",   # green
    "comms":        "#9B59B6",   # purple
    "motor_driver": "#E74C3C",   # red
    "display":      "#1ABC9C",   # teal
    "connector":    "#F39C12",   # amber
    "passive":      "#BDC3C7",   # light grey
    "default":      "#95A5A6",   # grey
}

CATEGORY_STROKE = {
    "mcu":          "#1A5FCC",
    "power":        "#C87D1A",
    "sensor":       "#2E8B3E",
    "comms":        "#6C3483",
    "motor_driver": "#A93226",
    "display":      "#148F77",
    "connector":    "#B7770D",
    "passive":      "#7F8C8D",
    "default":      "#5D6D7E",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def mm_to_px(val_mm):
    return val_mm * PX_PER_MM


def load_json(path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def category_of(comp):
    return comp.get("category", "default")


def comp_colour(comp):
    cat = category_of(comp)
    return CATEGORY_FILL.get(cat, CATEGORY_FILL["default"])


def comp_stroke_colour(comp):
    cat = category_of(comp)
    return CATEGORY_STROKE.get(cat, CATEGORY_STROKE["default"])


# ─── Overrides ────────────────────────────────────────────────────────────────

def apply_overrides(components, overrides):
    """
    Merge placement_overrides.json into components list.

    overrides format:
      { "U1": { "x_mm": 30, "y_mm": 20, "rotation_deg": 90 }, ... }
    """
    by_ref = {c["ref"]: c for c in components}
    for ref, changes in overrides.items():
        if ref in by_ref:
            by_ref[ref].update(changes)
    return list(by_ref.values())


# ─── Warning lookup ───────────────────────────────────────────────────────────

def build_warned_refs(warnings):
    """
    Return set of component refs that have validation warnings.
    warnings is the list from validation_warnings.json.
    Each warning may contain an 'affected_refs' list.
    """
    warned = set()
    if not warnings:
        return warned
    for w in warnings:
        for ref in w.get("affected_refs", []):
            warned.add(ref)
    return warned


# ─── SVG construction ─────────────────────────────────────────────────────────

def build_svg(placement, warnings_data, apply_overrides_flag):
    board   = placement["board"]
    comps   = placement["components"]
    mcu_ref = placement.get("mcu_ref")

    # Apply overrides if requested
    if apply_overrides_flag and "overrides" in placement:
        comps = apply_overrides(comps, placement["overrides"])

    w_mm = board["w_mm"]
    h_mm = board["h_mm"]
    w_px = mm_to_px(w_mm)
    h_px = mm_to_px(h_mm)

    canvas_w = w_px + 2 * MARGIN_PX
    canvas_h = h_px + 2 * MARGIN_PX

    warned_refs = build_warned_refs(warnings_data.get("warnings") if warnings_data else None)

    # Root SVG element
    svg = ET.Element("svg", {
        "xmlns":   "http://www.w3.org/2000/svg",
        "width":   str(canvas_w),
        "height":  str(canvas_h),
        "viewBox": f"0 0 {canvas_w} {canvas_h}",
    })

    # ── Background ──
    ET.SubElement(svg, "rect", {
        "x": "0", "y": "0",
        "width": str(canvas_w), "height": str(canvas_h),
        "fill": "#F0F0F0",
    })

    # Group: offset by MARGIN_PX so board coords start at origin
    g = ET.SubElement(svg, "g", {"transform": f"translate({MARGIN_PX},{MARGIN_PX})"})

    # ── Board outline ──
    ET.SubElement(g, "rect", {
        "x": "0", "y": "0",
        "width":  str(w_px),
        "height": str(h_px),
        "fill":   "#FFFDE7",         # cream PCB colour
        "stroke": "#212121",
        "stroke-width": str(BOARD_STROKE),
    })

    # ── Grid (1cm / 10mm) ──
    for x_mm in range(0, int(w_mm) + 1, 10):
        x_px = mm_to_px(x_mm)
        ET.SubElement(g, "line", {
            "x1": str(x_px), "y1": "0",
            "x2": str(x_px), "y2": str(h_px),
            "stroke": "#D0D0D0", "stroke-width": "0.5",
        })
    for y_mm in range(0, int(h_mm) + 1, 10):
        y_px = mm_to_px(y_mm)
        ET.SubElement(g, "line", {
            "x1": "0",    "y1": str(y_px),
            "x2": str(w_px), "y2": str(y_px),
            "stroke": "#D0D0D0", "stroke-width": "0.5",
        })

    # ── Ratsnest lines (star topology from MCU) ──
    mcu_comp = next((c for c in comps if c["ref"] == mcu_ref), None)
    if mcu_comp:
        mx = mm_to_px(mcu_comp["x_mm"])
        my = mm_to_px(mcu_comp["y_mm"])
        for c in comps:
            if c["ref"] == mcu_ref:
                continue
            cx = mm_to_px(c["x_mm"])
            cy = mm_to_px(c["y_mm"])
            ET.SubElement(g, "line", {
                "x1": str(mx), "y1": str(my),
                "x2": str(cx), "y2": str(cy),
                "stroke": "#AAAAAA",
                "stroke-width": str(RATSNEST_STROKE),
                "stroke-dasharray": "2,3",
                "opacity": "0.6",
            })

    # ── Component rectangles ──
    for c in comps:
        ref     = c["ref"]
        x_mm    = c["x_mm"]
        y_mm    = c["y_mm"]
        cw_mm   = c.get("width_mm",  5.0)
        ch_mm   = c.get("height_mm", 5.0)
        rot     = c.get("rotation_deg", 0)

        # Convert: placement stores centre; SVG rect uses top-left
        cx_px = mm_to_px(x_mm)
        cy_px = mm_to_px(y_mm)
        cw_px = mm_to_px(cw_mm)
        ch_px = mm_to_px(ch_mm)
        rect_x = cx_px - cw_px / 2
        rect_y = cy_px - ch_px / 2

        fill   = comp_colour(c)
        stroke = comp_stroke_colour(c)
        is_warned = ref in warned_refs

        # Group for rotation transform around component centre
        cg = ET.SubElement(g, "g", {
            "transform": f"rotate({rot},{cx_px},{cy_px})",
        })

        # Warning glow (drawn behind main rect)
        if is_warned:
            ET.SubElement(cg, "rect", {
                "x":      str(rect_x - WARN_STROKE),
                "y":      str(rect_y - WARN_STROKE),
                "width":  str(cw_px + 2 * WARN_STROKE),
                "height": str(ch_px + 2 * WARN_STROKE),
                "fill":   "none",
                "stroke": WARN_COLOUR,
                "stroke-width": str(WARN_STROKE * 2),
                "opacity": "0.8",
                "rx": "1", "ry": "1",
            })

        # Component body
        ET.SubElement(cg, "rect", {
            "x":      str(rect_x),
            "y":      str(rect_y),
            "width":  str(cw_px),
            "height": str(ch_px),
            "fill":   fill,
            "stroke": stroke,
            "stroke-width": str(COMP_STROKE),
            "opacity": "0.85",
            "rx": "1", "ry": "1",
        })

        # Pin 1 marker (small filled square at top-left of rotated rect)
        pin_size = 2
        ET.SubElement(cg, "rect", {
            "x":      str(rect_x),
            "y":      str(rect_y),
            "width":  str(pin_size),
            "height": str(pin_size),
            "fill":   stroke,
        })

        # Ref designator label (always horizontal — separate transform)
        label_x = cx_px
        label_y = cy_px + LABEL_FONT_SIZE * 0.35  # vertical centre
        ET.SubElement(g, "text", {
            "x":           str(label_x),
            "y":           str(label_y),
            "font-family": "monospace",
            "font-size":   str(LABEL_FONT_SIZE),
            "fill":        "#1A1A1A",
            "text-anchor": "middle",
            "font-weight": "bold",
        }).text = ref

    # ── Board dimension labels ──
    for attr, text, x, y, anchor in [
        ("", f"{w_mm:.0f}mm", w_px / 2, h_px + 14, "middle"),
        ("", f"{h_mm:.0f}mm", -10, h_px / 2,      "middle"),
    ]:
        t = ET.SubElement(g, "text", {
            "x":           str(x),
            "y":           str(y),
            "font-family": "sans-serif",
            "font-size":   "9",
            "fill":        "#555555",
            "text-anchor": anchor,
        })
        if x == -10:
            t.set("transform", f"rotate(-90,{x},{y})")
        t.text = text

    # ── Legend ──
    legend_categories = sorted(set(category_of(c) for c in comps))
    lx = canvas_w - MARGIN_PX + 2   # right of board — may clip; acceptable for preview
    ly = MARGIN_PX
    # Only show legend if there is room (canvas > 500px wide)
    if canvas_w > 500:
        for i, cat in enumerate(legend_categories):
            box_y = ly + i * 14
            ET.SubElement(svg, "rect", {
                "x": str(lx - MARGIN_PX - 80),
                "y": str(box_y),
                "width": "8", "height": "8",
                "fill": CATEGORY_FILL.get(cat, CATEGORY_FILL["default"]),
                "stroke": CATEGORY_STROKE.get(cat, CATEGORY_STROKE["default"]),
                "stroke-width": "1",
            })
            ET.SubElement(svg, "text", {
                "x": str(lx - MARGIN_PX - 68),
                "y": str(box_y + 7),
                "font-family": "sans-serif",
                "font-size": "8",
                "fill": "#333333",
            }).text = cat

    return svg


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python svg_preview.py <job_dir> [--overrides]")
        sys.exit(1)

    job_dir  = Path(sys.argv[1])
    use_overrides = "--overrides" in sys.argv

    placement_path = job_dir / "placement.json"
    if not placement_path.exists():
        print(f"ERROR: placement.json not found in {job_dir}")
        sys.exit(1)

    placement = load_json(placement_path)
    warnings  = load_json(job_dir / "validation_warnings.json")

    # Apply placement_overrides.json into the component list before rendering
    if use_overrides:
        overrides_data = load_json(job_dir / "placement_overrides.json")
        if overrides_data:
            placement["components"] = apply_overrides(
                placement["components"], overrides_data
            )

    svg = build_svg(placement, warnings, use_overrides)

    out_path = job_dir / "placement_preview.svg"
    tree = ET.ElementTree(svg)
    ET.indent(tree, space="  ")
    tree.write(str(out_path), encoding="utf-8", xml_declaration=True)

    w_mm = placement["board"]["w_mm"]
    h_mm = placement["board"]["h_mm"]
    n    = len(placement["components"])
    print(f"[svg_preview] Rendered {n} components on {w_mm}x{h_mm}mm board")
    print(f"[svg_preview] Saved to {out_path}")


if __name__ == "__main__":
    main()
