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
import re
import sys
import time
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR     = PROJECT_ROOT / "data"
COMPONENTS_PATH = DATA_DIR / "components.json"
PROFILES_PATH   = DATA_DIR / "placement_profiles.json"
WEIGHTS_PATH    = DATA_DIR / "placement_weights.json"

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

# ─── Net-based power check ────────────────────────────────────────────────────

_POWER_NETS = {"GND", "VCC_3V3", "VCC_5V", "VBAT", "VBAT_COIN", "VBUS", "GND_BATT"}

def _is_power_net(name):
    return name in _POWER_NETS


# ─── Learned weights ─────────────────────────────────────────────────────────

_DEFAULT_WEIGHTS = {
    "overlap": 200.0,
    "overlap_floor": 100.0,
    "zone_priority_scale": 0.3,
    "boundary": 100.0,
    "antenna_keepout": 200.0,
    "proximity": 5.0,
    "crystal": 50.0,
    "crystal_threshold_mm": 5.0,
    "decoupling": 30.0,
    "block_cohesion_passive": 0.3,
    "block_cohesion_active": 1.5,
    "block_separation_min_mm": 15.0,
    "block_separation_penalty": 2.0,
}


def load_learned_weights():
    """Load learned SA weights. Returns defaults if file doesn't exist."""
    try:
        if WEIGHTS_PATH.exists():
            with open(WEIGHTS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("learned", dict(_DEFAULT_WEIGHTS))
    except (json.JSONDecodeError, KeyError, IOError):
        pass
    return dict(_DEFAULT_WEIGHTS)


# ─── Profile matching and warm-start ─────────────────────────────────────────

MIN_SIMILARITY = 0.50


def load_profiles():
    """Load placement profiles. Returns [] if file doesn't exist."""
    try:
        if PROFILES_PATH.exists():
            with open(PROFILES_PATH, encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return []


def find_best_match(design_cids, board_w, board_h, profiles):
    """Find the best matching DRC-clean profile for a new design.
    Score = jaccard(component_id sets) * board_size_ratio.
    Returns (profile, similarity) or (None, 0.0)."""
    if not profiles:
        return None, 0.0

    design_area = board_w * board_h
    design_set = set(design_cids)
    best_profile = None
    best_sim = 0.0

    for profile in profiles:
        if not profile.get("outcome", {}).get("drc_clean", False):
            continue

        profile_set = set(profile["fingerprint"]["component_ids"])
        intersection = len(design_set & profile_set)
        union = len(design_set | profile_set)
        if union == 0:
            continue
        jaccard = intersection / union

        pw = profile["fingerprint"]["board_w_mm"]
        ph = profile["fingerprint"]["board_h_mm"]
        profile_area = pw * ph
        if profile_area > 0 and design_area > 0:
            size_ratio = min(design_area, profile_area) / max(design_area, profile_area)
        else:
            size_ratio = 0.0

        similarity = jaccard * size_ratio
        if similarity > best_sim:
            best_sim = similarity
            best_profile = profile

    if best_sim >= MIN_SIMILARITY:
        return best_profile, best_sim
    return None, 0.0


def warm_start_placement(components, profile, w, h, margin=3.0, parent_map=None):
    """Build initial placement from a matched profile.
    Components with matching component_id get profile positions (scaled).
    Unmatched components fall through to rule-based initial_placement."""
    profile_positions = profile.get("positions", {})
    placement = {}
    consumed = {}

    sorted_comps = sorted(
        components,
        key=lambda c: get_comp(c["component_id"]).get(
            "placement_priority",
            FALLBACK_PRIORITY.get(get_comp(c["component_id"]).get("category", ""), 9)
        )
    )

    unmatched = []

    for rc in sorted_comps:
        cid = rc["component_id"]
        pos_data = profile_positions.get(cid)

        if pos_data is None:
            unmatched.append(rc)
            continue

        # Handle single entry or list of entries
        if isinstance(pos_data, list):
            idx = consumed.get(cid, 0)
            if idx < len(pos_data):
                entry = pos_data[idx]
                consumed[cid] = idx + 1
            else:
                unmatched.append(rc)
                continue
        else:
            if cid in consumed:
                unmatched.append(rc)
                continue
            entry = pos_data
            consumed[cid] = 1

        # Scale relative position to new board dims
        x = entry["rx"] * w
        y = entry["ry"] * h
        rot = entry["rot"]

        # Respect edge constraints
        comp = get_comp(cid)
        edge = is_edge_zone(cid)
        is_conn = comp.get("category") == "connector"
        if edge and is_conn:
            rot = EDGE_ROTATION.get(edge, rot)

        # Clamp to board boundaries
        cw, ch = get_dims(cid)
        hw, hh = cw / 2, ch / 2
        x = max(margin + hw, min(w - margin - hw, x))
        y = max(margin + hh, min(h - margin - hh, y))

        placement[rc["ref"]] = {"x": round(x, 2), "y": round(y, 2), "rotation": rot}

    # Place unmatched components using rule-based initial_placement
    if unmatched:
        fallback = initial_placement(unmatched, w, h, margin=margin, parent_map=parent_map)
        for ref, pos in fallback.items():
            placement[ref] = pos

    return placement


# ─── Functional block classification ─────────────────────────────────────────

def classify_blocks(components, job_dir):
    """Group components into functional blocks based on net affinity.

    Components sharing non-power nets are adjacent in the affinity graph.
    BFS finds connected blocks. Single-component blocks merge into the
    nearest block by net affinity.

    Returns list of block dicts:
      [{"refs": [ref, ...], "zone": str, "category": str}, ...]
    """
    job_path = Path(job_dir)
    netlist_path = job_path / "netlist.json"
    if netlist_path.exists():
        with open(netlist_path, encoding="utf-8") as f:
            nets = json.load(f).get("nets", {})
    else:
        # No netlist yet — fall back to category-based blocks
        return _category_blocks(components)

    all_refs = {rc["ref"] for rc in components}
    ref_to_comp = {rc["ref"]: rc for rc in components}

    # Build adjacency graph from non-power nets
    adj = {ref: set() for ref in all_refs}
    ref_nets = {ref: set() for ref in all_refs}  # for affinity scoring

    for net_name, members in nets.items():
        if _is_power_net(net_name):
            continue
        net_refs = {m["ref"] for m in members if m["ref"] in all_refs}
        for r in net_refs:
            ref_nets[r].add(net_name)
        refs_list = list(net_refs)
        for i, a in enumerate(refs_list):
            for b in refs_list[i + 1:]:
                adj[a].add(b)
                adj[b].add(a)

    # BFS to find connected components → raw blocks
    visited = set()
    raw_blocks = []
    for ref in all_refs:
        if ref in visited:
            continue
        block = []
        queue = [ref]
        while queue:
            r = queue.pop(0)
            if r in visited:
                continue
            visited.add(r)
            block.append(r)
            for nb in adj[r]:
                if nb not in visited:
                    queue.append(nb)
        raw_blocks.append(block)

    # Merge small blocks (≤1 component) into best-matching larger block
    main_blocks = [b for b in raw_blocks if len(b) > 1]
    singletons = [b[0] for b in raw_blocks if len(b) == 1]

    if not main_blocks:
        # All singletons — fall back to category-based grouping
        return _category_blocks(components)

    for s_ref in singletons:
        best_idx = 0
        best_score = -1
        s_nets = ref_nets.get(s_ref, set())
        for i, block in enumerate(main_blocks):
            block_nets = set()
            for r in block:
                block_nets |= ref_nets.get(r, set())
            shared = len(s_nets & block_nets)
            if shared > best_score:
                best_score = shared
                best_idx = i
        main_blocks[best_idx].append(s_ref)

    # Classify each block by dominant category → assign zone
    blocks = []
    for block_refs in main_blocks:
        cats = {}
        for r in block_refs:
            rc = ref_to_comp.get(r)
            if rc:
                comp = get_comp(rc["component_id"])
                cat = comp.get("category", "passive")
                if cat != "passive":
                    cats[cat] = cats.get(cat, 0) + 1
        dominant = max(cats, key=cats.get) if cats else "passive"
        zone = FALLBACK_ZONE.get(dominant, "any")
        blocks.append({
            "refs": block_refs,
            "zone": zone,
            "category": dominant,
        })

    return blocks


def _category_blocks(components):
    """Fallback: group components by category when no netlist is available."""
    cat_groups = {}
    for rc in components:
        comp = get_comp(rc["component_id"])
        cat = comp.get("category", "passive")
        cat_groups.setdefault(cat, []).append(rc["ref"])
    blocks = []
    for cat, refs in cat_groups.items():
        blocks.append({
            "refs": refs,
            "zone": FALLBACK_ZONE.get(cat, "any"),
            "category": cat,
        })
    return blocks


# ─── Reference designator assignment ─────────────────────────────────────────

def assign_refs(components):
    """Wrapper around refdes.assign_refs for backward compatibility."""
    from refdes import assign_refs as _assign
    return _assign(components, load_db())


# ─── Parent map for auto-added components ────────────────────────────────────

def build_parent_map(components):
    """
    Determine which 'parent' component each auto-added part should sit near.
    Returns dict: child_ref → parent_ref.

    Rules:
      - USB support parts (auto_add_rule contains 'usb', or interfaces=['USB'])
        → parent is the USB connector
      - Decoupling caps → parent is the IC mentioned in 'reason'
      - I2C pull-ups → parent is the MCU (central I2C hub)
      - Otherwise → no parent (free placement)
    """
    parent_map = {}

    # Index: find connector and MCU refs
    connector_ref = None
    mcu_ref = None
    ref_by_cid = {}  # component_id → ref
    all_refs = {rc["ref"] for rc in components}
    for rc in components:
        ref_by_cid[rc["component_id"]] = rc["ref"]
        comp = get_comp(rc["component_id"])
        if comp.get("category") == "connector":
            connector_ref = rc["ref"]
        if comp.get("category") == "mcu":
            mcu_ref = rc["ref"]

    for rc in components:
        if not rc.get("auto_added"):
            continue

        comp = get_comp(rc["component_id"])
        role = comp.get("generic_role", "")
        rule = comp.get("auto_add_rule", "")
        ifaces = comp.get("interfaces", [])
        reason = rc.get("reason", "")

        # USB support → near connector
        if "usb" in rule.lower() or "USB" in ifaces:
            if connector_ref:
                parent_map[rc["ref"]] = connector_ref
                continue

        # Decoupling → near the IC they decouple
        if role in ("decoupling_100nf", "bulk_decoupling"):
            assigned = False
            # Try to find parent ref from "for Xn" in reason first
            m = re.search(r'\bfor\s+([A-Z]+\d+)\b', reason)
            if m and m.group(1) in all_refs:
                parent_map[rc["ref"]] = m.group(1)
                assigned = True
            if not assigned:
                # Try to find parent IC from reason text (display_name match)
                for other_rc in components:
                    if other_rc["ref"] == rc["ref"]:
                        continue
                    other_comp = get_comp(other_rc["component_id"])
                    name = other_comp.get("display_name", "")
                    if name and name.lower() in reason.lower():
                        parent_map[rc["ref"]] = other_rc["ref"]
                        assigned = True
                        break
            if not assigned:
                # Default: near MCU
                if mcu_ref:
                    parent_map[rc["ref"]] = mcu_ref
            continue

        # I2C pull-ups → near MCU
        if role == "i2c_pull_up":
            if mcu_ref:
                parent_map[rc["ref"]] = mcu_ref
            continue

        # Generic: auto-added parts with "for Xn" in reason → near that component
        # Covers buck regulator support passives ("Input cap for U2") and
        # MCU pull-ups ("Pull-up for U1 EN")
        m = re.search(r'\bfor\s+([A-Z]+\d+)\b', reason)
        if m:
            target = m.group(1)
            if target in all_refs:
                parent_map[rc["ref"]] = target
                continue

    return parent_map


# ─── Initial placement (rule-based) ──────────────────────────────────────────

EDGE_ZONES = {"edge_top", "edge_bottom", "edge_left", "edge_right"}

# Fixed rotation for edge-mount connectors so opening faces outward.
# KiCad USB-C footprints have opening facing +Y (downward) at 0 deg.
EDGE_ROTATION = {
    "edge_bottom": 0,    # opening faces down (board bottom)
    "edge_top":    180,  # opening faces up (board top)
    "edge_left":   90,   # opening faces left
    "edge_right":  270,  # opening faces right
}

def is_edge_zone(component_id):
    """Return the placement zone if it's an edge zone, else None."""
    comp = get_comp(component_id)
    zone = comp.get("placement_zone") or FALLBACK_ZONE.get(comp.get("category", ""), "any")
    return zone if zone in EDGE_ZONES else None

def zone_centre(zone, w, h, margin=3.0, edge_inset=0):
    """Return the target (x, y) centre for a given placement zone.
    For edge connectors, edge_inset (from component DB) sets exact distance from edge."""
    inner_w = w - 2 * margin
    inner_h = h - 2 * margin

    # For edge zones, use edge_inset if provided (connector-specific),
    # otherwise use half-board dimension as a rough centre target.
    ei = edge_inset if edge_inset > 0 else margin
    zones = {
        "edge_top":     (w / 2,           ei),
        "edge_bottom":  (w / 2,           h - ei),
        "edge_left":    (ei,              h / 2),
        "edge_right":   (w - ei,          h / 2),
        "centre":       (w / 2,           h / 2),
        "centre_right": (margin + inner_w * 0.7, h / 2),
        "power_column": (margin + inner_w * 0.15, h / 2),
        "any":          (w / 2,           h / 2),
    }
    return zones.get(zone, (w / 2, h / 2))


def initial_placement(components, w, h, margin=3.0, parent_map=None):
    """
    Place each component at the centre of its preferred zone,
    with a small random offset to avoid stacking.
    Auto-added children are placed near their parent component.
    Returns dict: ref → {x, y, rotation}
    """
    parent_map = parent_map or {}
    placement = {}
    zone_offsets = {}  # track how many components are in each zone
    child_offsets = {}  # track stagger per parent

    for rc in sorted(components, key=lambda c: get_comp(c["component_id"]).get("placement_priority",
                                                           FALLBACK_PRIORITY.get(get_comp(c["component_id"]).get("category",""), 9))):
        comp = get_comp(rc["component_id"])
        zone = comp.get("placement_zone") or FALLBACK_ZONE.get(comp.get("category", ""), "any")
        dims = comp.get("dimensions_mm") or FALLBACK_DIMS.get(comp.get("category", ""), FALLBACK_DIMS["default"])

        # If this component has a parent that's already placed, start near parent
        parent_ref = parent_map.get(rc["ref"])
        if parent_ref and parent_ref in placement:
            px = placement[parent_ref]["x"]
            py = placement[parent_ref]["y"]
            n_child = child_offsets.get(parent_ref, 0)
            child_offsets[parent_ref] = n_child + 1
            # Fan children around the parent, just outside the parent courtyard
            parent_cid = next((c["component_id"] for c in components if c["ref"] == parent_ref), None)
            if parent_cid:
                p_rot = placement[parent_ref].get("rotation", 0)
                pw, ph = get_effective_dims(parent_cid, p_rot)
            else:
                pw, ph = 10.0, 10.0
            child_cw, child_ch = get_dims(rc["component_id"])
            # Minimum radius to clear parent courtyard + child half-size + gap
            min_radius = max(pw, ph) / 2 + max(child_cw, child_ch) / 2 + 1.0
            angle = (n_child * 72 + 30) * math.pi / 180  # spread at 72° intervals
            radius = min_radius + n_child * 1.5
            x = px + radius * math.cos(angle)
            y = py + radius * math.sin(angle)
        else:
            edge_inset = comp.get("edge_inset_mm", 0)
            cx, cy = zone_centre(zone, w, h, margin, edge_inset=edge_inset)

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

        # Clamp to board.
        # - Connectors at edge: use edge_inset_mm (distance from origin to PCB edge)
        # - Other edge parts (MCU antenna): courtyard at edge (full hh inset)
        # - Interior parts: 3mm margin
        cw, ch = get_dims(rc["component_id"])
        hw = cw / 2
        hh = ch / 2
        edge = is_edge_zone(rc["component_id"])
        is_connector = comp.get("category") == "connector"
        edge_inset = comp.get("edge_inset_mm", 0)
        if edge and is_connector and edge_inset > 0:
            ei_x, ei_y = edge_inset, edge_inset
        elif edge:
            ei_x, ei_y = hw, hh    # courtyard flush with edge
        else:
            ei_x, ei_y = margin + hw, margin + hh
        x_min = ei_x if edge == "edge_left"   else margin + hw
        x_max = (w - ei_x) if edge == "edge_right"  else w - margin - hw
        y_min = ei_y if edge == "edge_top"    else margin + hh
        y_max = (h - ei_y) if edge == "edge_bottom"  else h - margin - hh
        # Antenna modules must stay near their edge to keep keepout off-board
        if comp.get("antenna_keepout_zone_local"):
            if edge == "edge_top":    y_max = min(y_max, hh + 3.0)
            elif edge == "edge_bottom": y_min = max(y_min, h - hh - 3.0)
        # Edge-mount connectors: lock perpendicular axis to edge position
        if edge and is_connector and edge_inset > 0:
            if edge in ("edge_top", "edge_bottom"):
                y = ei_y if edge == "edge_top" else h - ei_y
            elif edge in ("edge_left", "edge_right"):
                x = ei_x if edge == "edge_left" else w - ei_x
        x = max(x_min, min(x_max, x))
        y = max(y_min, min(y_max, y))

        # Only connectors get fixed rotation (opening faces outward).
        # MCU/antenna modules stay at 0° so antenna points toward edge.
        rot = EDGE_ROTATION.get(edge, 0) if (edge and is_connector) else 0
        placement[rc["ref"]] = {"x": round(x, 2), "y": round(y, 2), "rotation": rot}
        zone_offsets[zone] = n + 1

    return placement


# ─── Score function ───────────────────────────────────────────────────────────

def get_pos(ref, placement):
    p = placement.get(ref, {})
    return p.get("x", 0), p.get("y", 0)

def get_courtyard_center(component_id, placement_entry):
    """Get the effective center of the component courtyard in board coordinates.
    Accounts for footprint_center_offset_mm (origin != courtyard center, e.g. USB-C)."""
    x = placement_entry.get("x", 0)
    y = placement_entry.get("y", 0)
    rot = placement_entry.get("rotation", 0)
    comp = get_comp(component_id)
    offset = comp.get("footprint_center_offset_mm")
    if offset:
        ox, oy = offset["x"], offset["y"]
        rad = math.radians(rot)
        cos_r, sin_r = math.cos(rad), math.sin(rad)
        x += ox * cos_r - oy * sin_r
        y += ox * sin_r + oy * cos_r
    return x, y

def get_dims(component_id):
    comp = get_comp(component_id)
    dims = comp.get("dimensions_mm") or FALLBACK_DIMS.get(comp.get("category", ""), FALLBACK_DIMS["default"])
    # Default 0.5mm clearance — accounts for KiCad courtyard extensions.
    # Components with larger pad extensions (e.g. ESP32 module) should set
    # courtyard_clearance_mm explicitly in the DB.
    clearance = comp.get("courtyard_clearance_mm", 0.5)
    w = dims["width"]
    # For 3D package specs (length, width, height), "height" is Z-axis (physical
    # height above board), not Y-axis footprint extent.  Use "length" as the
    # Y-axis dimension when it exists; fall back to "height" for 2D specs.
    h = dims.get("length", dims["height"]) if "length" in dims else dims["height"]
    return w + clearance * 2, h + clearance * 2

def get_effective_dims(component_id, rotation):
    """Get courtyard-inclusive dimensions accounting for rotation.
    At 90 or 270 degrees, width and height are swapped."""
    cw, ch = get_dims(component_id)
    if rotation in (90, 270):
        return ch, cw
    return cw, ch

def overlap_penalty(ref_a, comp_a, ref_b, comp_b, placement, wt):
    """Penalise overlapping component courtyards heavily (rotation-aware).
    Uses courtyard center (not footprint origin) for asymmetric connectors."""
    ax, ay = get_courtyard_center(comp_a["component_id"], placement.get(ref_a, {}))
    bx, by = get_courtyard_center(comp_b["component_id"], placement.get(ref_b, {}))
    rot_a = placement.get(ref_a, {}).get("rotation", 0)
    rot_b = placement.get(ref_b, {}).get("rotation", 0)
    aw, ah = get_effective_dims(comp_a["component_id"], rot_a)
    bw, bh = get_effective_dims(comp_b["component_id"], rot_b)

    dx = abs(ax - bx)
    dy = abs(ay - by)
    min_dx = (aw + bw) / 2
    min_dy = (ah + bh) / 2

    if dx < min_dx and dy < min_dy:
        overlap_x = min_dx - dx
        overlap_y = min_dy - dy
        return max(overlap_x * overlap_y * wt["overlap"], wt["overlap_floor"])
    return 0.0

def zone_penalty(ref, component_id, placement, w, h, wt, margin=3.0):
    """Penalise components that drift far from their preferred zone."""
    comp = get_comp(component_id)
    zone = comp.get("placement_zone") or FALLBACK_ZONE.get(comp.get("category", ""), "any")
    if zone == "any":
        return 0.0

    x, y = get_pos(ref, placement)
    zx, zy = zone_centre(zone, w, h, margin)
    dist = math.hypot(x - zx, y - zy)
    priority = comp.get("placement_priority", FALLBACK_PRIORITY.get(comp.get("category", ""), 9))
    weight = max(0.1, (10 - priority) * wt["zone_priority_scale"])
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


def block_cohesion_score(components, placement, blocks, wt):
    """Penalise block spread (intra-block) and block crowding (inter-block).

    Replaces star topology when blocks are available.
    - Intra-block: components should cluster tightly around block centroid.
    - Inter-block: blocks should maintain >= separation minimum.
    """
    if not blocks:
        return 0.0
    s = 0.0
    ref_to_comp = {rc["ref"]: rc for rc in components}
    centroids = []

    for block in blocks:
        refs = [r for r in block["refs"] if r in placement]
        if not refs:
            continue

        bx = sum(get_pos(r, placement)[0] for r in refs) / len(refs)
        by = sum(get_pos(r, placement)[1] for r in refs) / len(refs)
        centroids.append((bx, by))

        for r in refs:
            x, y = get_pos(r, placement)
            d = math.hypot(x - bx, y - by)
            rc = ref_to_comp.get(r)
            if rc:
                cat = get_comp(rc["component_id"]).get("category", "passive")
                cat_wt = wt["block_cohesion_passive"] if cat == "passive" else wt["block_cohesion_active"]
            else:
                cat_wt = 1.0
            s += d * cat_wt

    min_sep = wt["block_separation_min_mm"]
    for i, c1 in enumerate(centroids):
        for c2 in centroids[i + 1:]:
            d = math.hypot(c1[0] - c2[0], c1[1] - c2[1])
            if d < min_sep:
                s += (min_sep - d) * wt["block_separation_penalty"]

    return s


def boundary_penalty(ref, component_id, placement, w, h, wt, margin=3.0):
    """Penalise components whose courtyard extends beyond the board boundary (rotation-aware).
    Edge-zone components are allowed to be flush with their designated edge.
    Uses courtyard center for asymmetric connectors."""
    x, y = get_courtyard_center(component_id, placement.get(ref, {}))
    rot = placement.get(ref, {}).get("rotation", 0)
    cw, ch = get_effective_dims(component_id, rot)
    hw, hh = cw / 2, ch / 2
    edge = is_edge_zone(component_id)
    penalty = 0.0
    # left, right, top, bottom overhang
    # Connectors at edge: no penalty on their edge side (body overhangs)
    # Other edge components: courtyard at edge (penalize beyond board)
    is_conn = get_comp(component_id).get("category") == "connector"
    no_pen = edge and is_conn  # only connectors overhang
    overhangs = [
        0 if no_pen and edge == "edge_left"   else (margin + hw) - x,
        0 if no_pen and edge == "edge_right"  else x + hw - (w - margin),
        0 if no_pen and edge == "edge_top"    else (margin + hh) - y,
        0 if no_pen and edge == "edge_bottom" else y + hh - (h - margin),
    ]
    for over in overhangs:
        if over > 0:
            penalty += over * over * wt["boundary"]
    return penalty


def antenna_keepout_penalty(components, placement, wt):
    """Penalise components placed inside the antenna keepout zone of any module.

    Uses antenna_keepout_zone_local (footprint-local rectangle from KiCad .kicad_mod)
    when available.  Falls back to the legacy antenna_keepout_mm estimate.

    Rotation transforms the local rectangle:
      rot=0   -> no transform (antenna toward -Y / top)
      rot=90  -> rotate 90 CW
      rot=180 -> rotate 180
      rot=270 -> rotate 270 CW
    """
    penalty = 0.0
    keepout_modules = []
    for rc in components:
        comp = get_comp(rc["component_id"])
        zone = comp.get("antenna_keepout_zone_local")
        keepout_dist = comp.get("antenna_keepout_mm", 0)
        if zone or keepout_dist > 0:
            keepout_modules.append((rc, comp, zone, keepout_dist))

    for rc_mod, comp_mod, zone, keepout_dist in keepout_modules:
        ref_mod = rc_mod["ref"]
        mx, my = get_pos(ref_mod, placement)
        rot = placement.get(ref_mod, {}).get("rotation", 0)

        if zone:
            # Use real footprint-local keepout rectangle, rotated to board coords
            lx0, ly0 = zone["x_min"], zone["y_min"]
            lx1, ly1 = zone["x_max"], zone["y_max"]
            corners = [(lx0, ly0), (lx1, ly0), (lx1, ly1), (lx0, ly1)]
            rad = math.radians(rot)
            cos_r, sin_r = math.cos(rad), math.sin(rad)
            xs, ys = [], []
            for cx, cy in corners:
                rx = cx * cos_r - cy * sin_r
                ry = cx * sin_r + cy * cos_r
                xs.append(mx + rx)
                ys.append(my + ry)
            kx_min, kx_max = min(xs), max(xs)
            ky_min, ky_max = min(ys), max(ys)
        else:
            # Legacy fallback: narrow keepout from module dimensions
            cw, ch = get_dims(rc_mod["component_id"])
            hw, hh = cw / 2, ch / 2
            if rot == 0:
                kx_min, kx_max = mx - hw, mx + hw
                ky_min, ky_max = my - hh - keepout_dist, my - hh
            elif rot == 90:
                kx_min, kx_max = mx - hh - keepout_dist, mx - hh
                ky_min, ky_max = my - hw, my + hw
            elif rot == 180:
                kx_min, kx_max = mx - hw, mx + hw
                ky_min, ky_max = my + hh, my + hh + keepout_dist
            else:
                kx_min, kx_max = mx + hh, mx + hh + keepout_dist
                ky_min, ky_max = my - hw, my + hw

        # Check all other components against keepout
        for rc_other in components:
            if rc_other["ref"] == ref_mod:
                continue
            ox, oy = get_pos(rc_other["ref"], placement)
            rot_o = placement.get(rc_other["ref"], {}).get("rotation", 0)
            ow, oh = get_effective_dims(rc_other["component_id"], rot_o)
            ohw, ohh = ow / 2, oh / 2

            # AABB overlap between keepout zone and component courtyard
            dx = min(ox + ohw, kx_max) - max(ox - ohw, kx_min)
            dy = min(oy + ohh, ky_max) - max(oy - ohh, ky_min)
            if dx > 0 and dy > 0:
                penalty += dx * dy * wt["antenna_keepout"]

    return penalty


def proximity_penalty(components, placement, parent_map, wt):
    """Penalise auto-added components that are far from their parent.
    Target: just outside parent courtyard edge + 3mm margin.
    Also penalises being INSIDE the parent courtyard (overlap handled elsewhere
    but this reinforces separation)."""
    if not parent_map:
        return 0.0
    penalty = 0.0
    # Build cid lookup
    ref_to_cid = {rc["ref"]: rc["component_id"] for rc in components}
    for rc in components:
        parent_ref = parent_map.get(rc["ref"])
        if not parent_ref or parent_ref not in placement:
            continue
        cx, cy = get_pos(rc["ref"], placement)
        px, py = get_pos(parent_ref, placement)
        dist = math.hypot(cx - px, cy - py)
        # Target distance: half-diagonal of parent courtyard + 3mm
        parent_cid = ref_to_cid.get(parent_ref, "")
        rot_p = placement.get(parent_ref, {}).get("rotation", 0)
        pw, ph = get_effective_dims(parent_cid, rot_p)
        target = math.hypot(pw, ph) / 2 + 3.0
        if dist > target:
            excess = dist - target
            penalty += excess * excess * wt["proximity"]
    return penalty


def crystal_proximity_penalty(components, placement, mcu_ref, wt):
    """Penalise crystals placed far from the MCU.
    Industry best practice: crystal ≤5mm from MCU pins.
    Penalty: quadratic beyond threshold."""
    if not mcu_ref or mcu_ref not in placement:
        return 0.0
    penalty = 0.0
    threshold = wt["crystal_threshold_mm"]
    mx, my = get_pos(mcu_ref, placement)
    for rc in components:
        cid = rc["component_id"]
        if "crystal" not in cid.lower():
            continue
        ref = rc["ref"]
        if ref not in placement:
            continue
        cx, cy = get_pos(ref, placement)
        dist = math.hypot(cx - mx, cy - my)
        if dist > threshold:
            excess = dist - threshold
            penalty += excess * excess * wt["crystal"]
    return penalty


def decoupling_proximity_penalty(components, placement, parent_map, wt):
    """Penalise decoupling caps placed far from their parent IC.
    Industry best practice: decoupling ≤3mm, bulk ≤5mm from IC.
    Penalty: quadratic beyond threshold."""
    if not parent_map:
        return 0.0
    penalty = 0.0
    for rc in components:
        ref = rc["ref"]
        cid = rc["component_id"]
        comp = get_comp(cid)
        role = comp.get("generic_role", "")
        if "decoupling" not in role:
            continue
        parent_ref = parent_map.get(ref)
        if not parent_ref or parent_ref not in placement or ref not in placement:
            continue
        threshold = 5.0 if "bulk" in role else 3.0
        cx, cy = get_pos(ref, placement)
        px, py = get_pos(parent_ref, placement)
        dist = math.hypot(cx - px, cy - py)
        if dist > threshold:
            excess = dist - threshold
            penalty += excess * excess * wt["decoupling"]
    return penalty


def score(components, placement, w, h, mcu_ref, parent_map=None, blocks=None,
          wt=None):
    """Combined score: block cohesion (or wire length) + zone + overlap +
    boundary + antenna keepout + proximity + crystal + decoupling."""
    if wt is None:
        wt = _DEFAULT_WEIGHTS

    # Use block cohesion when blocks available, wire length as fallback
    if blocks:
        s = block_cohesion_score(components, placement, blocks, wt)
    else:
        s = wire_length_score(components, placement, mcu_ref)

    for rc in components:
        s += zone_penalty(rc["ref"], rc["component_id"], placement, w, h, wt)
        s += boundary_penalty(rc["ref"], rc["component_id"], placement, w, h, wt)

    for i, a in enumerate(components):
        for b in components[i + 1:]:
            s += overlap_penalty(a["ref"], a, b["ref"], b, placement, wt)

    s += antenna_keepout_penalty(components, placement, wt)
    s += proximity_penalty(components, placement, parent_map or {}, wt)
    s += crystal_proximity_penalty(components, placement, mcu_ref, wt)
    s += decoupling_proximity_penalty(components, placement, parent_map or {}, wt)

    return s


# ─── Simulated annealing ──────────────────────────────────────────────────────

def _component_overlaps_any(ref, comp_id, candidate, components, min_gap=0.15):
    """Check if component `ref` overlaps any other placed component.
    Returns True if overlap exists (hard constraint).
    min_gap: minimum clearance between courtyard edges (mm)."""
    ax, ay = get_courtyard_center(comp_id, candidate.get(ref, {}))
    rot_a = candidate.get(ref, {}).get("rotation", 0)
    aw, ah = get_effective_dims(comp_id, rot_a)

    for rc in components:
        if rc["ref"] == ref:
            continue
        b_ref = rc["ref"]
        b_cid = rc["component_id"]
        bx, by = get_courtyard_center(b_cid, candidate.get(b_ref, {}))
        rot_b = candidate.get(b_ref, {}).get("rotation", 0)
        bw, bh = get_effective_dims(b_cid, rot_b)

        dx = abs(ax - bx)
        dy = abs(ay - by)
        min_dx = (aw + bw) / 2 + min_gap
        min_dy = (ah + bh) / 2 + min_gap

        if dx < min_dx and dy < min_dy:
            return True
    return False


def simulated_annealing(components, placement, w, h, mcu_ref, time_cap=10.0,
                        parent_map=None, blocks=None, weights=None):
    """
    SA optimisation of component placement.
    Moves: translate, rotate 90 deg, swap two components.
    Hard constraint: moves that create overlap are always rejected.
    Returns (best_placement, initial_score, final_score, iterations).
    """
    if len(components) <= 1:
        return placement, 0.0, 0.0, 0

    margin   = 3.0
    current  = {ref: dict(pos) for ref, pos in placement.items()}
    best     = {ref: dict(pos) for ref, pos in current.items()}
    wt = weights or _DEFAULT_WEIGHTS
    cur_s    = score(components, current, w, h, mcu_ref, parent_map, blocks, wt)
    best_s   = cur_s
    init_s   = cur_s

    T  = 80.0     # initial temperature
    T_min = 0.1
    alpha = 0.9993  # cooling rate (slower → more iterations to resolve overlaps)
    t0 = time.monotonic()
    itr = 0
    MAX_ITR = 15000

    refs = [rc["ref"] for rc in components]
    cid_by_ref = {rc["ref"]: rc["component_id"] for rc in components}
    # Lock rotation for edge-zone components:
    # - Connectors: opening faces outward (EDGE_ROTATION)
    # - Antenna modules: antenna faces edge (rotation=0 at edge_top)
    edge_locked = {rc["ref"] for rc in components if is_edge_zone(rc["component_id"])}

    while T > T_min and itr < MAX_ITR:
        if itr % 200 == 0 and time.monotonic() - t0 > time_cap:
            break
        itr += 1

        candidate = {ref: dict(pos) for ref, pos in current.items()}
        move = random.random()

        if move < 0.5:
            # Translate a random component
            ref = random.choice(refs)
            comp_id = next(rc["component_id"] for rc in components if rc["ref"] == ref)
            rot = candidate[ref]["rotation"]
            ew, eh = get_effective_dims(comp_id, rot)
            hw = ew / 2
            hh = eh / 2
            sigma = max(5.0, T * 0.25)
            new_x = candidate[ref]["x"] + random.gauss(0, sigma)
            new_y = candidate[ref]["y"] + random.gauss(0, sigma)
            edge = is_edge_zone(comp_id)
            comp_sa = get_comp(comp_id)
            is_conn = comp_sa.get("category") == "connector"
            edge_inset = comp_sa.get("edge_inset_mm", 0)
            if edge and is_conn and edge_inset > 0:
                ei_x, ei_y = edge_inset, edge_inset
            elif edge:
                ei_x, ei_y = hw, hh
            else:
                ei_x, ei_y = margin + hw, margin + hh
            x_min = ei_x if edge == "edge_left"  else margin + hw
            x_max = (w - ei_x) if edge == "edge_right" else w - margin - hw
            y_min = ei_y if edge == "edge_top"   else margin + hh
            y_max = (h - ei_y) if edge == "edge_bottom" else h - margin - hh
            # Antenna modules must stay near their edge to keep keepout off-board
            if comp_sa.get("antenna_keepout_zone_local"):
                if edge == "edge_top":    y_max = min(y_max, hh + 3.0)
                elif edge == "edge_bottom": y_min = max(y_min, h - hh - 3.0)
            # Edge-mount connectors: lock perpendicular axis to edge position
            if edge and is_conn and edge_inset > 0:
                if edge in ("edge_top", "edge_bottom"):
                    fixed_y = ei_y if edge == "edge_top" else h - ei_y
                    new_y = fixed_y
                elif edge in ("edge_left", "edge_right"):
                    fixed_x = ei_x if edge == "edge_left" else w - ei_x
                    new_x = fixed_x
            new_x = max(x_min, min(x_max, new_x))
            new_y = max(y_min, min(y_max, new_y))
            candidate[ref] = {"x": round(new_x, 2), "y": round(new_y, 2), "rotation": rot}

        elif move < 0.7:
            # Rotate 90 deg — skip edge-locked parts (connectors face outward)
            ref = random.choice(refs)
            if ref in edge_locked:
                continue
            comp_id = next(rc["component_id"] for rc in components if rc["ref"] == ref)
            new_rot = (candidate[ref]["rotation"] + 90) % 360
            ew, eh = get_effective_dims(comp_id, new_rot)
            hw, hh = ew / 2, eh / 2
            edge = is_edge_zone(comp_id)
            comp_sa = get_comp(comp_id)
            is_conn = comp_sa.get("category") == "connector"
            edge_inset = comp_sa.get("edge_inset_mm", 0)
            if edge and is_conn and edge_inset > 0:
                ei_x, ei_y = edge_inset, edge_inset
            elif edge:
                ei_x, ei_y = hw, hh
            else:
                ei_x, ei_y = margin + hw, margin + hh
            x_min = ei_x if edge == "edge_left"  else margin + hw
            x_max = (w - ei_x) if edge == "edge_right" else w - margin - hw
            y_min = ei_y if edge == "edge_top"   else margin + hh
            y_max = (h - ei_y) if edge == "edge_bottom" else h - margin - hh
            if comp_sa.get("antenna_keepout_zone_local"):
                if edge == "edge_top":    y_max = min(y_max, hh + 3.0)
                elif edge == "edge_bottom": y_min = max(y_min, h - hh - 3.0)
            cx = max(x_min, min(x_max, candidate[ref]["x"]))
            cy = max(y_min, min(y_max, candidate[ref]["y"]))
            candidate[ref] = {"x": round(cx, 2), "y": round(cy, 2), "rotation": new_rot}

        else:
            # Swap two random components' positions (skip edge-locked pairs)
            if len(refs) < 2:
                continue
            r1, r2 = random.sample(refs, 2)
            if r1 in edge_locked or r2 in edge_locked:
                continue
            candidate[r1], candidate[r2] = candidate[r2], candidate[r1]

        # ── Hard constraint: reject moves that create component overlap ──
        # Identify which ref(s) were moved
        if move < 0.5:
            moved_refs = [ref]
        elif move < 0.7:
            moved_refs = [ref]
        else:
            moved_refs = [r1, r2]

        overlap_found = False
        for mr in moved_refs:
            if _component_overlaps_any(mr, cid_by_ref[mr], candidate, components):
                overlap_found = True
                break

        if overlap_found:
            T *= alpha
            continue  # always reject overlapping moves

        new_s = score(components, candidate, w, h, mcu_ref, parent_map, blocks, wt)
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

    # Deterministic seed — derived from component list for reproducibility.
    # Same design always produces the same placement.
    seed_str = json.dumps(sorted(
        rc.get("component_id", "") for rc in resolved.get("resolved_components", [])
    ))
    random.seed(hash(seed_str) & 0xFFFFFFFF)

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

    # 2. Build parent map (auto-added → parent component)
    parent_map = build_parent_map(components)

    # 3. Load learned weights
    weights = load_learned_weights()
    print(f"  Weights: {'learned' if WEIGHTS_PATH.exists() else 'defaults'}")

    # 4. Classify functional blocks from netlist (if available)
    blocks = classify_blocks(components, job_path)
    if blocks:
        block_summary = ", ".join(f"{b['category']}({len(b['refs'])})" for b in blocks)
        print(f"  Blocks: {block_summary}")

    # 5. Attempt warm-start from matching profile
    warm_start_info = None
    design_cids = sorted(set(rc["component_id"] for rc in components))
    profiles = load_profiles()
    matched_profile, similarity = find_best_match(design_cids, w, h, profiles)

    if matched_profile:
        print(f"  Profile match: {matched_profile['id']} (similarity: {similarity:.0%})")
        placement = warm_start_placement(
            components, matched_profile, w, h, parent_map=parent_map
        )
        warm_start_info = {
            "matched_profile": matched_profile["id"],
            "similarity": round(similarity, 3),
        }
    else:
        # 5b. Rule-based initial placement (children start near parents)
        placement = initial_placement(components, w, h, parent_map=parent_map)

    # 6. Find MCU ref for wire-length scoring
    mcu_id  = resolved.get("mcu", {}).get("id")
    mcu_ref = next((rc["ref"] for rc in components if rc["component_id"] == mcu_id), None)

    # 7. SA optimisation
    best_placement, init_s, final_s, itr = simulated_annealing(
        components, placement, w, h, mcu_ref, parent_map=parent_map,
        blocks=blocks, weights=weights
    )

    improvement_pct = max(0.0, (init_s - final_s) / init_s * 100) if init_s > 0 else 0.0

    # 8. Build output
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
        "weights_used": weights,
    }
    if warm_start_info:
        result["warm_start"] = warm_start_info

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
