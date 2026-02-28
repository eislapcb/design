"""
Eisla — Component Placement Engine (python/placement.py)

Session 9. Runs after validator.py, before svg_preview.py.

Algorithm:
  1. Load resolved components + board config
  2. Assign reference designators (U1, C1, R1, J1, ...)
  3. Rule-based initial placement (respect placement_zone from components.json)
  4. Simulated annealing optimisation (minimise star-topology wire length
     from MCU centroid to each peripheral, penalise zone violations + overlaps)
  5. Write placement.json to job dir

Usage:
    python placement.py <job_dir>

Input files (in job_dir):
    resolved.json  — full resolver output (resolved_components list)
    board.json     — board config { dimensions_mm, layers, power_source }

Output (in job_dir):
    placement.json — component positions, rotations, ref designators
"""

import json
import math
import random
import sys
import time
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR     = PROJECT_ROOT / "data"
COMPONENTS_PATH = DATA_DIR / "components.json"

# ─── Data loading ─────────────────────────────────────────────────────────────

_db = None

def load_db():
    global _db
    if _db is None:
        with open(COMPONENTS_PATH, encoding="utf-8") as f:
            _db = json.load(f)
    return _db

def get_comp(component_id):
    return load_db().get(component_id, {})

# ─── Fallback dimensions by category (when not in DB) ────────────────────────

FALLBACK_DIMS = {
    "mcu":          {"width": 10.0, "height": 10.0},
    "power":        {"width": 6.0,  "height": 4.0},
    "sensor":       {"width": 5.0,  "height": 4.0},
    "comms":        {"width": 16.0, "height": 16.0},
    "motor_driver": {"width": 5.0,  "height": 5.0},
    "display":      {"width": 30.0, "height": 25.0},
    "connector":    {"width": 8.0,  "height": 6.0},
    "passive":      {"width": 1.0,  "height": 0.5},
    "default":      {"width": 5.0,  "height": 5.0},
}

FALLBACK_ZONE = {
    "mcu":          "centre",
    "power":        "power_column",
    "sensor":       "centre_right",
    "comms":        "edge_top",
    "motor_driver": "edge_bottom",
    "display":      "edge_top",
    "connector":    "edge_bottom",
    "passive":      "any",
}

FALLBACK_PRIORITY = {
    "mcu": 1, "comms": 2, "connector": 3, "power": 4,
    "motor_driver": 5, "display": 6, "sensor": 7, "passive": 9,
}

# ─── Reference designator assignment ─────────────────────────────────────────

def assign_refs(components):
    """
    Assign unique reference designators to each resolved component instance.
    Uses ref_designator_prefix from DB, falling back to category-based defaults.
    Returns list of component dicts with 'ref' field added.
    """
    PREFIX_FALLBACK = {
        "mcu": "U", "power": "U", "sensor": "U", "comms": "U",
        "motor_driver": "U", "display": "LCD", "connector": "J",
        "passive": "?",
    }
    SUB_PREFIX = {
        "capacitor": "C", "resistor": "R", "diode": "D", "diode_flyback": "D",
        "led": "LED", "mosfet_n": "Q", "mosfet_p": "Q", "tvs_esd": "D",
        "tvs_diode": "D", "crystal": "X", "inductor": "L", "fuse": "F",
        "test_point": "TP", "fiducial": "FID",
    }

    counters = {}
    result   = []

    for rc in components:
        comp = get_comp(rc["component_id"])
        prefix = (
            comp.get("ref_designator_prefix") or
            SUB_PREFIX.get(comp.get("subcategory", "")) or
            PREFIX_FALLBACK.get(comp.get("category", ""), "U")
        )
        n = counters.get(prefix, 0) + 1
        counters[prefix] = n
        result.append({**rc, "ref": f"{prefix}{n}"})

    return result


# ─── Initial placement (rule-based) ──────────────────────────────────────────

def zone_centre(zone, w, h, margin=3.0):
    """Return the target (x, y) centre for a given placement zone."""
    inner_w = w - 2 * margin
    inner_h = h - 2 * margin

    zones = {
        "edge_top":     (w / 2,           margin + inner_h * 0.1),
        "edge_bottom":  (w / 2,           margin + inner_h * 0.9),
        "edge_left":    (margin + inner_w * 0.1, h / 2),
        "edge_right":   (margin + inner_w * 0.9, h / 2),
        "centre":       (w / 2,           h / 2),
        "centre_right": (margin + inner_w * 0.7, h / 2),
        "power_column": (margin + inner_w * 0.15, h / 2),
        "any":          (w / 2,           h / 2),
    }
    return zones.get(zone, (w / 2, h / 2))


def initial_placement(components, w, h, margin=3.0):
    """
    Place each component at the centre of its preferred zone,
    with a small random offset to avoid stacking.
    Returns dict: ref → {x, y, rotation}
    """
    placement = {}
    zone_offsets = {}  # track how many components are in each zone

    for rc in sorted(components, key=lambda c: get_comp(c["component_id"]).get("placement_priority",
                                                           FALLBACK_PRIORITY.get(get_comp(c["component_id"]).get("category",""), 9))):
        comp = get_comp(rc["component_id"])
        zone = comp.get("placement_zone") or FALLBACK_ZONE.get(comp.get("category", ""), "any")
        dims = comp.get("dimensions_mm") or FALLBACK_DIMS.get(comp.get("category", ""), FALLBACK_DIMS["default"])

        cx, cy = zone_centre(zone, w, h, margin)

        # Stagger components in the same zone
        n = zone_offsets.get(zone, 0)
        row = n // 4
        col = n % 4
        step_x = max(dims["width"]  + 2.0, 6.0)
        step_y = max(dims["height"] + 2.0, 6.0)
        offset_x = (col - 1.5) * step_x
        offset_y = (row - 0.5) * step_y

        x = cx + offset_x + random.uniform(-1.0, 1.0)
        y = cy + offset_y + random.uniform(-1.0, 1.0)

        # Clamp to board with margin
        hw = dims["width"]  / 2
        hh = dims["height"] / 2
        x = max(margin + hw, min(w - margin - hw, x))
        y = max(margin + hh, min(h - margin - hh, y))

        placement[rc["ref"]] = {"x": round(x, 2), "y": round(y, 2), "rotation": 0}
        zone_offsets[zone] = n + 1

    return placement


# ─── Score function ───────────────────────────────────────────────────────────

def get_pos(ref, placement):
    p = placement.get(ref, {})
    return p.get("x", 0), p.get("y", 0)

def get_dims(component_id):
    comp = get_comp(component_id)
    dims = comp.get("dimensions_mm") or FALLBACK_DIMS.get(comp.get("category", ""), FALLBACK_DIMS["default"])
    clearance = comp.get("courtyard_clearance_mm", 0.25)
    return dims["width"] + clearance * 2, dims["height"] + clearance * 2

def overlap_penalty(ref_a, comp_a, ref_b, comp_b, placement):
    """Penalise overlapping component courtyards heavily."""
    ax, ay = get_pos(ref_a, placement)
    bx, by = get_pos(ref_b, placement)
    aw, ah = get_dims(comp_a["component_id"])
    bw, bh = get_dims(comp_b["component_id"])

    dx = abs(ax - bx)
    dy = abs(ay - by)
    min_dx = (aw + bw) / 2
    min_dy = (ah + bh) / 2

    if dx < min_dx and dy < min_dy:
        # Overlap area
        overlap_x = min_dx - dx
        overlap_y = min_dy - dy
        return overlap_x * overlap_y * 50.0  # heavy penalty
    return 0.0

def zone_penalty(ref, component_id, placement, w, h, margin=3.0):
    """Penalise components that drift far from their preferred zone."""
    comp = get_comp(component_id)
    zone = comp.get("placement_zone") or FALLBACK_ZONE.get(comp.get("category", ""), "any")
    if zone == "any":
        return 0.0

    x, y = get_pos(ref, placement)
    zx, zy = zone_centre(zone, w, h, margin)
    dist = math.hypot(x - zx, y - zy)
    priority = comp.get("placement_priority", FALLBACK_PRIORITY.get(comp.get("category", ""), 9))
    # Higher priority components get stronger zone enforcement
    weight = max(0.1, (10 - priority) * 0.3)
    return dist * weight

def wire_length_score(components, placement, mcu_ref):
    """
    Star topology: sum of distances from MCU centroid to each other component.
    Weighted by component category (ICs closer to MCU than passives).
    """
    if not mcu_ref or mcu_ref not in placement:
        return 0.0

    mx, my = get_pos(mcu_ref, placement)
    total = 0.0

    WEIGHTS = {
        "mcu": 0.0, "power": 0.8, "sensor": 1.0, "comms": 1.2,
        "motor_driver": 0.6, "display": 0.5, "connector": 0.3,
        "passive": 0.1,
    }

    for rc in components:
        if rc["ref"] == mcu_ref:
            continue
        comp = get_comp(rc["component_id"])
        cat  = comp.get("category", "passive")
        w    = WEIGHTS.get(cat, 0.5)
        x, y = get_pos(rc["ref"], placement)
        total += math.hypot(x - mx, y - my) * w

    return total

def score(components, placement, w, h, mcu_ref):
    """Combined score: wire length + zone penalties + overlap penalties."""
    s = wire_length_score(components, placement, mcu_ref)

    for rc in components:
        s += zone_penalty(rc["ref"], rc["component_id"], placement, w, h)

    for i, a in enumerate(components):
        for b in components[i + 1:]:
            s += overlap_penalty(a["ref"], a, b["ref"], b, placement)

    return s


# ─── Simulated annealing ──────────────────────────────────────────────────────

def simulated_annealing(components, placement, w, h, mcu_ref, time_cap=10.0):
    """
    SA optimisation of component placement.
    Moves: translate, rotate 90 deg, swap two components.
    Returns (best_placement, initial_score, final_score, iterations).
    """
    if len(components) <= 1:
        return placement, 0.0, 0.0, 0

    margin   = 3.0
    current  = {ref: dict(pos) for ref, pos in placement.items()}
    best     = {ref: dict(pos) for ref, pos in current.items()}
    cur_s    = score(components, current, w, h, mcu_ref)
    best_s   = cur_s
    init_s   = cur_s

    T  = 80.0     # initial temperature
    T_min = 0.5
    alpha = 0.997  # cooling rate
    t0 = time.monotonic()
    itr = 0
    MAX_ITR = 8000

    refs = [rc["ref"] for rc in components]

    while T > T_min and itr < MAX_ITR:
        if itr % 200 == 0 and time.monotonic() - t0 > time_cap:
            break
        itr += 1

        candidate = {ref: dict(pos) for ref, pos in current.items()}
        move = random.random()

        if move < 0.5:
            # Translate a random component
            ref = random.choice(refs)
            comp = get_comp(next(rc["component_id"] for rc in components if rc["ref"] == ref))
            dims = comp.get("dimensions_mm") or FALLBACK_DIMS.get(comp.get("category", ""), FALLBACK_DIMS["default"])
            hw = dims["width"] / 2
            hh = dims["height"] / 2
            sigma = max(3.0, T * 0.15)
            new_x = candidate[ref]["x"] + random.gauss(0, sigma)
            new_y = candidate[ref]["y"] + random.gauss(0, sigma)
            new_x = max(margin + hw, min(w - margin - hw, new_x))
            new_y = max(margin + hh, min(h - margin - hh, new_y))
            candidate[ref] = {"x": round(new_x, 2), "y": round(new_y, 2), "rotation": candidate[ref]["rotation"]}

        elif move < 0.7:
            # Rotate 90 deg
            ref = random.choice(refs)
            r = candidate[ref]["rotation"]
            candidate[ref] = {**candidate[ref], "rotation": (r + 90) % 360}

        else:
            # Swap two random components' positions
            if len(refs) < 2:
                continue
            r1, r2 = random.sample(refs, 2)
            candidate[r1], candidate[r2] = candidate[r2], candidate[r1]

        new_s = score(components, candidate, w, h, mcu_ref)
        delta = new_s - cur_s

        if delta < 0 or random.random() < math.exp(-delta / T):
            current = candidate
            cur_s   = new_s
            if cur_s < best_s:
                best   = {ref: dict(pos) for ref, pos in current.items()}
                best_s = cur_s

        T *= alpha

    improvement_pct = max(0.0, (init_s - best_s) / init_s * 100) if init_s > 0 else 0.0
    print(f"  SA: {itr} iterations, T={T:.2f}, score {init_s:.1f} -> {best_s:.1f} ({improvement_pct:.1f}% improvement)")
    return best, init_s, best_s, itr


# ─── Main ─────────────────────────────────────────────────────────────────────

def run(job_dir):
    job_path = Path(job_dir)

    with open(job_path / "resolved.json", encoding="utf-8") as f:
        resolved = json.load(f)

    with open(job_path / "board.json", encoding="utf-8") as f:
        board = json.load(f)

    dims = board.get("dimensions_mm", [100, 80])
    w, h = float(dims[0]), float(dims[1])

    resolved_components = resolved.get("resolved_components", [])
    if not resolved_components:
        print("No components to place.")
        placement_data = {"board": {"w_mm": w, "h_mm": h}, "components": [],
                          "score": {"initial": 0, "final": 0, "improvement_pct": 0}, "iterations": 0}
        with open(job_path / "placement.json", "w", encoding="utf-8") as f:
            json.dump(placement_data, f, indent=2)
        return

    # 1. Assign ref designators
    print(f"Placing {len(resolved_components)} components on {w}x{h}mm board...")
    components = assign_refs(resolved_components)

    # 2. Initial rule-based placement
    placement = initial_placement(components, w, h)

    # 3. Find MCU ref for wire-length scoring
    mcu_id  = resolved.get("mcu", {}).get("id")
    mcu_ref = next((rc["ref"] for rc in components if rc["component_id"] == mcu_id), None)

    # 4. SA optimisation
    best_placement, init_s, final_s, itr = simulated_annealing(
        components, placement, w, h, mcu_ref
    )

    improvement_pct = max(0.0, (init_s - final_s) / init_s * 100) if init_s > 0 else 0.0

    # 5. Build output
    output_components = []
    for rc in components:
        comp = get_comp(rc["component_id"])
        dims_c = comp.get("dimensions_mm") or FALLBACK_DIMS.get(comp.get("category", ""), FALLBACK_DIMS["default"])
        pos  = best_placement.get(rc["ref"], {"x": w/2, "y": h/2, "rotation": 0})
        output_components.append({
            "component_id":  rc["component_id"],
            "ref":           rc["ref"],
            "display_name":  rc.get("display_name", rc["component_id"]),
            "category":      comp.get("category", "passive"),
            "subcategory":   comp.get("subcategory", ""),
            "x_mm":          round(pos["x"], 2),
            "y_mm":          round(pos["y"], 2),
            "rotation_deg":  pos["rotation"],
            "width_mm":      dims_c["width"],
            "height_mm":     dims_c["height"],
            "placement_zone": comp.get("placement_zone", "any"),
        })

    result = {
        "board":      {"w_mm": w, "h_mm": h},
        "components": output_components,
        "mcu_ref":    mcu_ref,
        "score": {
            "initial":         round(init_s, 1),
            "final":           round(final_s, 1),
            "improvement_pct": round(improvement_pct, 1),
        },
        "iterations": itr,
    }

    out_path = job_path / "placement.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Placement written to {out_path}")
    print(f"  {len(output_components)} components placed, {improvement_pct:.1f}% SA improvement")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python placement.py <job_dir>")
        sys.exit(1)
    run(sys.argv[1])
