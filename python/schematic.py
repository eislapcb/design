"""
Eisla -- KiCad Schematic Generator (python/schematic.py)

Generates board.kicad_sch in KiCad 6+ s-expression format.
Parses installed KiCad symbol libraries for pin data and lib_symbols.
Groups components into functional blocks by signal connectivity.
Places labels and power symbols at calculated pin endpoints for connectivity.

First stage in the pipeline — runs before netlist, placement, and PCB.
Assigns reference designators, generates the netlist, then builds the schematic.

Input (in job_dir):
  resolved.json    -- resolved component list from resolver

Output (in job_dir):
  board.kicad_sch  -- KiCad schematic
  netlist.json     -- logical netlist (consumed by placement + PCB stages)

Usage:
    python schematic.py <job_dir>
"""

import json
import re
import sys
import uuid
from pathlib import Path

SCRIPT_DIR      = Path(__file__).parent
PROJECT_ROOT    = SCRIPT_DIR.parent
COMPONENTS_PATH = PROJECT_ROOT / "data" / "components.json"
SYM_LIB_BASE    = Path("C:/Program Files/KiCad/9.0/share/kicad/symbols")

POWER_NET_KW = ("GND", "VCC", "3V3", "5V", "VBAT", "VBUS")
POWER_SYM = {
    "GND": "power:GND", "VCC_3V3": "power:+3.3V", "VCC_5V": "power:+5V",
    "VBUS": "power:VBUS", "VBAT": "power:+BATT",
}


def uid():
    return str(uuid.uuid4())


def q(s):
    return f'"{s}"'


def load_json(path):
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def is_power_net(name):
    return any(kw in name for kw in POWER_NET_KW)


# ═══ Synthetic symbol helpers (for components missing from KiCad libs) ═══════

def _gather_db_pins(db_entry):
    """Extract all known pins from a component DB entry.
    Returns {pad_str: name_str}.
    """
    result = {}
    pins_data = db_entry.get("pins", {})

    # Power pins
    for pw in pins_data.get("power", []):
        name = pw.get("name", pw.get("net", "PWR"))
        pads = pw.get("pins", [])
        if not pads and "pin" in pw:
            pads = [pw["pin"]]
        for p in pads:
            ps = str(p)
            if ps not in result:
                result[ps] = name

    # Interface pins
    for _ikey, iface in pins_data.get("interfaces", {}).items():
        if isinstance(iface, dict):
            iface_pins = iface.get("pins", iface)
            for sig, pad in iface_pins.items():
                if sig in ("notes", "note"):
                    continue
                ps = str(pad)
                if ps not in result:
                    result[ps] = sig

    # Terminal pins (array of dicts: [{"name": "G", "pins": ["1"]}, ...])
    terminals = pins_data.get("terminals", [])
    if isinstance(terminals, list):
        for term in terminals:
            name = term.get("name", "")
            pads = term.get("pins", [])
            if not pads and "pin" in term:
                pads = [term["pin"]]
            for p in pads:
                ps = str(p)
                if ps not in result:
                    result[ps] = name
    elif isinstance(terminals, dict):
        for name, data in terminals.items():
            ps = str(data.get("pin", "")) if isinstance(data, dict) else str(data)
            if ps and ps not in result:
                result[ps] = name

    # Control pins (array or dict)
    control = pins_data.get("control", [])
    if isinstance(control, list):
        for ctrl in control:
            name = ctrl.get("name", "")
            ps = str(ctrl.get("pin", ""))
            if ps and ps not in result:
                result[ps] = name
    elif isinstance(control, dict):
        for name, data in control.items():
            ps = str(data.get("pin", "")) if isinstance(data, dict) else str(data)
            if ps and ps not in result:
                result[ps] = name

    # GPIO-like pins (regulators use this for EN, BST, FB)
    for g in pins_data.get("gpio", []):
        if isinstance(g, dict):
            name = g.get("name", "")
            ps = str(g.get("pin", ""))
            if ps and ps not in result:
                result[ps] = name

    # Output pins
    output = pins_data.get("output", {})
    if isinstance(output, dict):
        for key, val in output.items():
            if key in ("net", "note"):
                continue
            ps = str(val)
            if ps not in result:
                result[ps] = key

    # Key pins
    key_pins = pins_data.get("key_pins", {})
    if isinstance(key_pins, dict):
        for name, data in key_pins.items():
            ps = str(data.get("pin", "")) if isinstance(data, dict) else str(data)
            if ps and ps not in result:
                result[ps] = name

    return result


def _synth_symbol_block(lib_id, pin_map):
    """Generate a synthetic KiCad symbol s-expression for a missing library symbol.

    Returns (block_str, pin_data_dict) where pin_data_dict matches
    the format of get_sym_pins(): {pad: {x, y, angle, length, name, number}}.
    """
    lib, part = lib_id.split(":", 1)

    sorted_pins = sorted(pin_map.items(), key=lambda kv: (
        not kv[0].isdigit(),
        int(kv[0]) if kv[0].isdigit() else 0,
        kv[0],
    ))

    n = len(sorted_pins)
    left_n = (n + 1) // 2
    pin_spacing = 2.54
    box_h = max(left_n, n - left_n) * pin_spacing + 2.54
    box_w = 10.16
    half_h = box_h / 2
    pin_len = 2.54

    pin_data = {}
    pin_lines = []

    for i, (pad, name) in enumerate(sorted_pins[:left_n]):
        y = round(half_h - 2.54 - i * pin_spacing, 2)
        x = round(-(box_w / 2) - pin_len, 2)
        pin_data[pad] = {
            "x": x, "y": y, "angle": 0, "length": pin_len,
            "name": name, "number": pad,
        }
        pin_lines.append(
            f'(pin passive line (at {x} {y} 0) (length {pin_len})\n'
            f'  (name "{name}" (effects (font (size 1.27 1.27))))\n'
            f'  (number "{pad}" (effects (font (size 1.27 1.27)))))'
        )

    for i, (pad, name) in enumerate(sorted_pins[left_n:]):
        y = round(half_h - 2.54 - i * pin_spacing, 2)
        x = round((box_w / 2) + pin_len, 2)
        pin_data[pad] = {
            "x": x, "y": y, "angle": 180, "length": pin_len,
            "name": name, "number": pad,
        }
        pin_lines.append(
            f'(pin passive line (at {x} {y} 180) (length {pin_len})\n'
            f'  (name "{name}" (effects (font (size 1.27 1.27))))\n'
            f'  (number "{pad}" (effects (font (size 1.27 1.27)))))'
        )

    bx1, by1 = round(-box_w / 2, 2), round(half_h, 2)
    bx2, by2 = round(box_w / 2, 2), round(-half_h, 2)
    ref_y = round(half_h + 1.27, 2)
    val_y = round(-half_h - 1.27, 2)

    pin_block = "\n".join("  " + l for l in pin_lines)
    block = (
        f'(symbol "{lib}:{part}"\n'
        f'(pin_names (offset 1.016))\n'
        f'(exclude_from_sim no)\n'
        f'(in_bom yes)\n'
        f'(on_board yes)\n'
        f'(property "Reference" "U" (at 0 {ref_y} 0)\n'
        f'  (effects (font (size 1.27 1.27))))\n'
        f'(property "Value" "{part}" (at 0 {val_y} 0)\n'
        f'  (effects (font (size 1.27 1.27))))\n'
        f'(property "Footprint" "" (at 0 0 0)\n'
        f'  (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'(property "Datasheet" "~" (at 0 0 0)\n'
        f'  (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'(symbol "{part}_0_1"\n'
        f'  (rectangle (start {bx1} {by1}) (end {bx2} {by2})\n'
        f'    (stroke (width 0.254) (type default))\n'
        f'    (fill (type background))))\n'
        f'(symbol "{part}_1_1"\n'
        f'{pin_block})\n'
        f')'
    )

    return block, pin_data


def power_lib_id(net):
    if net in POWER_SYM:
        return POWER_SYM[net]
    for kw, sym in [("GND", "power:GND"), ("3V3", "power:+3.3V"),
                     ("5V", "power:+5V"), ("VBAT", "power:+BATT"),
                     ("VBUS", "power:VBUS")]:
        if kw in net:
            return sym
    return "power:PWR_FLAG"


# ═══ Symbol library parser ═══════════════════════════════════════════════════

_lib_cache = {}   # lib_name -> file text
_sym_cache = {}   # (lib, part) -> {block, pins, extends} | None


def _read_lib(lib_name):
    if lib_name in _lib_cache:
        return _lib_cache[lib_name]
    path = SYM_LIB_BASE / f"{lib_name}.kicad_sym"
    if not path.exists():
        _lib_cache[lib_name] = None
        return None
    _lib_cache[lib_name] = path.read_text(encoding="utf-8")
    return _lib_cache[lib_name]


def _extract_block(text, start):
    """Extract balanced-paren block starting at or after `start`."""
    i = start
    while i < len(text) and text[i] != '(':
        i += 1
    if i >= len(text):
        return None
    depth, begin = 0, i
    while i < len(text):
        c = text[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[begin:i + 1]
        elif c == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                if text[i] == '\\':
                    i += 1
                i += 1
        i += 1
    return None


def extract_symbol(lib_name, part_name):
    """Extract a symbol definition + pin data from a KiCad .kicad_sym file."""
    key = (lib_name, part_name)
    if key in _sym_cache:
        return _sym_cache[key]

    text = _read_lib(lib_name)
    if not text:
        _sym_cache[key] = None
        return None

    # Find top-level symbol (single tab indent, exact name match)
    target = f'\t(symbol "{part_name}"'
    idx = text.find(target)
    if idx != -1:
        # Verify next char after closing quote isn't part of a longer name
        end_q = idx + len(target)
        if end_q < len(text) and text[end_q] not in ('\n', '\r', ' ', '\t'):
            idx = -1

    if idx == -1:
        _sym_cache[key] = None
        return None

    block = _extract_block(text, idx)
    if not block:
        _sym_cache[key] = None
        return None

    # Check for extends
    ext = re.search(r'\(extends\s+"([^"]+)"\)', block)
    extends = ext.group(1) if ext else None

    # Parse pins
    pins = []
    pin_re = re.compile(
        r'\(pin\s+\w+\s+\w+'
        r'.*?\(at\s+([\-\d.]+)\s+([\-\d.]+)\s+(\d+)\)'
        r'.*?\(length\s+([\-\d.]+)\)'
        r'.*?\(name\s+"([^"]*)"'
        r'.*?\(number\s+"([^"]*)"',
        re.DOTALL
    )
    for m in pin_re.finditer(block):
        pins.append({
            "x": float(m.group(1)), "y": float(m.group(2)),
            "angle": int(m.group(3)), "length": float(m.group(4)),
            "name": m.group(5), "number": m.group(6),
        })

    result = {"block": block, "pins": pins, "extends": extends}
    _sym_cache[key] = result
    return result


def get_sym_pins(kicad_symbol):
    """Get pin data for a symbol like 'Device:R'. Returns {number: pin_dict}."""
    if ":" not in kicad_symbol:
        return {}
    lib, part = kicad_symbol.split(":", 1)
    data = extract_symbol(lib, part)
    if not data:
        return {}
    pins = data["pins"]
    # If extended symbol has no pins, get from parent
    if data["extends"] and not pins:
        parent = extract_symbol(lib, data["extends"])
        if parent:
            pins = parent["pins"]
    return {p["number"]: p for p in pins}


def _qualify_block(block, lib_name, part_name):
    """Add library prefix to the top-level symbol name only.

    KiCad requires the parent symbol in lib_symbols to be qualified
    (e.g. "Battery_Management:DW01A") but sub-symbols must keep their
    original unqualified names (e.g. "DW01A_0_1", "DW01A_1_1").
    """
    qname = f"{lib_name}:{part_name}"
    block = re.sub(
        rf'\(symbol "{re.escape(part_name)}"(?![\w_])',
        f'(symbol "{qname}"',
        block,
        count=1,
    )
    return block


def _flatten_extends(parent_block, parent_name, child_name):
    """Create a standalone symbol by copying parent content, renaming to child.

    KiCad cannot resolve (extends "...") in embedded lib_symbols, so we
    copy the parent's full definition (graphics, pins, sub-symbols) and
    rename all symbol references from parent to child.
    """
    # Rename sub-symbols first: "Parent_0_1" → "Child_0_1"
    flat = parent_block.replace(
        f'(symbol "{parent_name}_', f'(symbol "{child_name}_'
    )
    # Rename top-level symbol (exact name, not sub-symbols)
    flat = re.sub(
        rf'\(symbol "{re.escape(parent_name)}"(?![\w_])',
        f'(symbol "{child_name}"',
        flat,
        count=1,
    )
    return flat


def build_lib_symbols(sym_ids, synth_blocks=None):
    """Build the (lib_symbols ...) section."""
    entries = []
    done = set()
    for sym_id in sorted(sym_ids):
        if sym_id in done or ":" not in sym_id:
            continue
        lib, part = sym_id.split(":", 1)
        data = extract_symbol(lib, part)
        if not data:
            continue
        done.add(sym_id)
        if data["extends"]:
            # Flatten: copy parent content and rename to child.
            # Do NOT emit (extends ...) — KiCad can't resolve it in
            # embedded lib_symbols context.
            pdata = extract_symbol(lib, data["extends"])
            if pdata:
                flat = _flatten_extends(pdata["block"], data["extends"], part)
                entries.append(_qualify_block(flat, lib, part))
            # Parent is only included if directly used (already in sym_ids)
        else:
            entries.append(_qualify_block(data["block"], lib, part))

    # Append synthetic blocks for symbols not found in KiCad libraries
    if synth_blocks:
        for sym_id in sorted(synth_blocks):
            if sym_id not in done:
                done.add(sym_id)
                entries.append(synth_blocks[sym_id])

    if not entries:
        return ""
    # Re-indent each block for embedding
    parts = []
    for block in entries:
        lines = block.split("\n")
        # Strip common leading whitespace (tabs from library, spaces from synth)
        stripped = [l.lstrip("\t ") for l in lines]
        indented = "\n".join("    " + s for s in stripped)
        parts.append(indented)
    return "  (lib_symbols\n" + "\n".join(parts) + "\n  )"


# ═══ Pin position calculator ═════════════════════════════════════════════════

def pin_pos(pin, sx, sy, rot=0):
    """
    Schematic position of a pin's connection point.
    Library Y-up → schematic Y-down: negate py.
    Then apply rotation (clockwise degrees).
    """
    px, py = pin["x"], pin["y"]
    if rot == 0:    return (round(sx + px, 2), round(sy - py, 2))
    if rot == 90:   return (round(sx + py, 2), round(sy + px, 2))
    if rot == 180:  return (round(sx - px, 2), round(sy + py, 2))
    if rot == 270:  return (round(sx - py, 2), round(sy - px, 2))
    return (round(sx + px, 2), round(sy - py, 2))


# ═══ Component grouping ══════════════════════════════════════════════════════

def group_components(components, nets):
    """Group components by shared signal nets (excluding power nets)."""
    refs = [c["ref"] for c in components]
    ref_set = set(refs)
    adj = {r: set() for r in refs}

    for net, members in nets.items():
        if is_power_net(net):
            continue
        mrefs = [m["ref"] for m in members if m["ref"] in ref_set]
        for i in range(len(mrefs)):
            for j in range(i + 1, len(mrefs)):
                adj[mrefs[i]].add(mrefs[j])
                adj[mrefs[j]].add(mrefs[i])

    # BFS connected components
    visited = set()
    groups = []
    for r in refs:
        if r in visited:
            continue
        grp, queue = [], [r]
        while queue:
            n = queue.pop()
            if n in visited:
                continue
            visited.add(n)
            grp.append(n)
            queue.extend(adj[n] - visited)
        groups.append(grp)

    # Merge singletons into best-matching group
    main = [g for g in groups if len(g) > 1]
    orphans = [g[0] for g in groups if len(g) == 1]
    if not main:
        return [refs]
    for orph in orphans:
        best, best_sc = main[0], 0
        for net, members in nets.items():
            mrefs = {m["ref"] for m in members}
            if orph not in mrefs:
                continue
            for g in main:
                sc = len(mrefs & set(g))
                if sc > best_sc:
                    best_sc, best = sc, g
        best.append(orph)
    return main


# ═══ Layout engine ════════════════════════════════════════════════════════════

GRID = 2.54   # KiCad default grid (mm)


def snap(v):
    """Snap a coordinate to the 2.54mm grid."""
    return round(round(v / GRID) * GRID, 2)


def _sym_height(cid, db):
    """Estimate symbol height in mm from pin data (includes padding for labels)."""
    comp = db.get(cid, {})
    sym = comp.get("kicad_symbol", "")
    pins = get_sym_pins(sym)
    if pins:
        ys = [p["y"] for p in pins.values()]
        return max(ys) - min(ys) + 15
    cat = comp.get("category", "")
    return 65 if cat in ("mcu", "connector") else 20


def _parent_map(grp_refs, nets, c_map, db):
    """Map each passive in a group to its parent anchor IC via net affinity."""
    anchors = []
    passives = []
    for r in grp_refs:
        cid = c_map[r].get("component_id", "")
        cat = db.get(cid, {}).get("category", "")
        if cat == "passive":
            passives.append(r)
        else:
            anchors.append(r)

    # Sort anchors: MCU first, then connectors, sensors, power, etc.
    order = {"mcu": 0, "connector": 1, "sensor": 2, "power": 3, "comms": 4}
    anchors.sort(key=lambda r: (
        order.get(db.get(c_map[r].get("component_id", ""), {}).get("category", ""), 5), r
    ))

    if not anchors:
        # All passives — treat first as anchor
        return grp_refs[:1], grp_refs[1:], {p: grp_refs[0] for p in grp_refs[1:]}

    pmap = {}
    for pref in passives:
        best, best_sc = anchors[0], 0
        for aref in anchors:
            sc = 0
            for members in nets.values():
                mrefs = {m["ref"] for m in members}
                if pref in mrefs and aref in mrefs:
                    sc += 1
            if sc > best_sc:
                best_sc, best = sc, aref
        pmap[pref] = best

    return anchors, passives, pmap


SHEET_MAX_Y = snap(275)    # A3 landscape (297mm) minus bottom margin
COL_START_Y = snap(50)     # top margin
COL_WIDTH   = snap(100)    # horizontal space per column
CHILD_X_OFF = snap(50)     # children offset from anchor


def layout(groups, components, nets, db):
    """Assign schematic positions with passives clustered near their parent IC.

    Wraps to a new column when vertical space runs out.
    Returns {ref: (x, y, rot)}.
    """
    c_map = {c["ref"]: c for c in components}
    pos = {}
    x = snap(60)

    for grp in groups:
        anchors, passives, pmap = _parent_map(grp, nets, c_map, db)

        # Group passives by parent anchor
        children = {a: [] for a in anchors}
        for p in passives:
            children[pmap[p]].append(p)

        y = COL_START_Y
        for aref in anchors:
            cid = c_map[aref].get("component_id", "")
            ah = _sym_height(cid, db)

            # Wrap to new column if this anchor would overflow the page
            if y + ah > SHEET_MAX_Y and y > COL_START_Y:
                x = snap(x + COL_WIDTH)
                y = COL_START_Y

            # Place anchor
            ay = snap(y + ah / 2)
            pos[aref] = (x, ay, 0)

            # Place children stacked to the right of anchor
            cx = snap(x + CHILD_X_OFF)
            cy = snap(y)
            for cref in children[aref]:
                ccid = c_map[cref].get("component_id", "")
                ch = _sym_height(ccid, db)
                pos[cref] = (cx, snap(cy + ch / 2), 0)
                cy = snap(cy + ch + 10)

            # Advance y past the taller of anchor vs its children stack
            y = snap(max(y + ah + 20, cy + 10))

        x = snap(x + COL_WIDTH)
    return pos


# ═══ Schematic element formatters ════════════════════════════════════════════

def fmt_sym(ref, comp, sx, sy, rot, pin_nums, pin_lookup, sym_uuid, root_uuid):
    """Format a component symbol instance."""
    lib_id = comp.get("kicad_symbol", "Device:Module")
    val = comp.get("mpn", comp.get("display_name", ref))
    fp = comp.get("kicad_footprint", "")

    # Position reference above topmost pin, value below bottommost
    if pin_lookup:
        max_py = max(p["y"] for p in pin_lookup.values())
        min_py = min(p["y"] for p in pin_lookup.values())
        ref_y = snap(sy - max_py - 3)
        val_y = snap(sy - min_py + 3)
    else:
        ref_y, val_y = snap(sy - 2.54), snap(sy + 2.54)

    lines = [
        '  (symbol',
        f'    (lib_id {q(lib_id)})',
        f'    (at {sx} {sy} {rot})',
        '    (unit 1)',
        '    (exclude_from_sim no)',
        '    (in_bom yes)',
        '    (on_board yes)',
        '    (dnp no)',
        f'    (uuid {q(sym_uuid)})',
        f'    (property "Reference" {q(ref)} (at {sx} {ref_y} 0)',
        '      (effects (font (size 1.27 1.27))))',
        f'    (property "Value" {q(val)} (at {sx} {val_y} 0)',
        '      (effects (font (size 1.27 1.27))))',
        f'    (property "Footprint" {q(fp)} (at {sx} {sy} 0)',
        '      (effects (font (size 1.27 1.27)) (hide yes)))',
    ]
    for pn in pin_nums:
        lines.append(f'    (pin {q(str(pn))} (uuid {q(uid())}))')
    lines.append('    (instances')
    lines.append('      (project ""')
    lines.append(f'        (path "/{root_uuid}"')
    lines.append(f'          (reference {q(ref)})')
    lines.append('          (unit 1))))')
    lines.append('  )')
    return '\n'.join(lines)


def fmt_pwr(net, x, y, idx, pwr_uuid, root_uuid):
    """Format a power symbol instance."""
    lib = power_lib_id(net)
    ref = f"#PWR{idx:03d}"
    return '\n'.join([
        '  (symbol',
        f'    (lib_id {q(lib)})',
        f'    (at {x} {y} 0)',
        '    (unit 1)',
        '    (exclude_from_sim no)',
        '    (in_bom no)',
        '    (on_board yes)',
        '    (dnp no)',
        f'    (uuid {q(pwr_uuid)})',
        f'    (property "Reference" {q(ref)} (at {x} {y} 0)',
        '      (effects (font (size 1.27 1.27)) (hide yes)))',
        f'    (property "Value" {q(net)} (at {x} {round(y + 2, 2)} 0)',
        '      (effects (font (size 1.27 1.27))))',
        f'    (pin "1" (uuid {q(uid())}))',
        '    (instances',
        '      (project ""',
        f'        (path "/{root_uuid}"',
        f'          (reference {q(ref)})',
        '          (unit 1))))',
        '  )',
    ])


def fmt_label(net, x, y, rot=0):
    """Format a global label. rot: 0=right-facing, 180=left-facing."""
    justify = "right" if rot == 180 else "left"
    return '\n'.join([
        f'  (global_label {q(net)}',
        '    (shape input)',
        f'    (at {x} {y} {rot})',
        f'    (effects (font (size 1.27 1.27)) (justify {justify}))',
        f'    (uuid {q(uid())})',
        f'    (property "Intersheet References" "" (at {x} {y} 0)',
        '      (effects (font (size 1.27 1.27)) (hide yes)))',
        '  )',
    ])


def fmt_wire(x1, y1, x2, y2):
    """Format a wire segment connecting two points."""
    return '\n'.join([
        '  (wire',
        f'    (pts (xy {x1} {y1}) (xy {x2} {y2}))',
        '    (stroke (width 0) (type default))',
        f'    (uuid {q(uid())})',
        '  )',
    ])


# ═══ Sheet classification ════════════════════════════════════════════════════

SHEET_DEFS = [
    ("Power Supply",    {"power"}),
    ("MCU",             {"mcu"}),
    ("Communications",  {"comms"}),
    ("Motor Control",   {"motor_driver"}),
    ("Sensors",         {"sensor"}),
    ("Connectors",      {"connector"}),
]

MAX_SHEETS = 6


def assign_sheets(components, nets, db):
    """Assign components to functional sheets by category.

    Returns list of (sheet_name, [component_dicts]).
    Small sheets (<3 components) are merged into the nearest sheet.
    Passives follow their parent IC's sheet (via net affinity).
    """
    c_map = {c["ref"]: c for c in components}
    ref_to_cat = {}
    for c in components:
        cid = c.get("component_id", "")
        cat = db.get(cid, {}).get("category", "passive")
        ref_to_cat[c["ref"]] = cat

    # Assign non-passive components to sheets
    sheet_refs = {name: [] for name, _ in SHEET_DEFS}
    unassigned = []

    for c in components:
        cat = ref_to_cat[c["ref"]]
        if cat == "passive":
            unassigned.append(c)
            continue
        placed = False
        for name, cats in SHEET_DEFS:
            if cat in cats:
                sheet_refs[name].append(c)
                placed = True
                break
        if not placed:
            unassigned.append(c)

    # Assign passives to their parent IC's sheet via net affinity
    ref_to_sheet = {}
    for name, comps in sheet_refs.items():
        for c in comps:
            ref_to_sheet[c["ref"]] = name

    for c in unassigned:
        best_sheet = _find_sheet_by_affinity(c["ref"], nets, ref_to_sheet)
        if best_sheet:
            sheet_refs[best_sheet].append(c)
        else:
            # Default to MCU sheet
            sheet_refs["MCU"].append(c)

    # Remove empty sheets
    sheets = [(name, comps) for name, comps in sheet_refs.items() if comps]

    # Merge tiny sheets (<3 components) into largest nearby sheet
    if len(sheets) > 1:
        merged = []
        for name, comps in sheets:
            if len(comps) < 3 and merged:
                # Merge into largest sheet
                largest = max(merged, key=lambda s: len(s[1]))
                largest[1].extend(comps)
            else:
                merged.append([name, comps])
        sheets = [(n, c) for n, c in merged]

    # If only 1 sheet, don't use hierarchical — just use flat
    return sheets


def _find_sheet_by_affinity(ref, nets, ref_to_sheet):
    """Find which sheet a component belongs to via shared nets."""
    sheet_scores = {}
    for net_name, members in nets.items():
        if is_power_net(net_name):
            continue
        member_refs = {m["ref"] for m in members}
        if ref not in member_refs:
            continue
        for mr in member_refs:
            if mr == ref:
                continue
            sheet = ref_to_sheet.get(mr)
            if sheet:
                sheet_scores[sheet] = sheet_scores.get(sheet, 0) + 1
    if sheet_scores:
        return max(sheet_scores, key=sheet_scores.get)
    return None


def _slugify(name):
    """Convert sheet name to filename-safe slug."""
    return name.lower().replace(" ", "_").replace("/", "_")


# ═══ Hierarchical sheet builders ═════════════════════════════════════════════

def build_root_sheet(sheets, db):
    """Build the root hierarchical schematic with sheet symbols."""
    root_uuid = uid()
    out = []
    out.append('(kicad_sch')
    out.append('  (version 20250114)')
    out.append('  (generator "eisla")')
    out.append('  (generator_version "9.0")')
    out.append(f'  (uuid {q(root_uuid)})')
    out.append('  (paper "A3")')
    out.append('')

    # No lib_symbols needed in root (only sheet references)
    # Place sheet symbols in a grid layout
    x_start = 50.0
    y_start = 40.0
    sheet_w = 60.0
    sheet_h = 30.0
    col_gap = 80.0
    row_gap = 50.0
    cols = 3

    for i, (name, comps) in enumerate(sheets):
        col = i % cols
        row = i // cols
        sx = snap(x_start + col * col_gap)
        sy = snap(y_start + row * row_gap)
        fname = _slugify(name) + ".kicad_sch"

        out.append(f'  (sheet (at {sx} {sy}) (size {sheet_w} {sheet_h})')
        out.append(f'    (stroke (width 0.2) (type solid) (color 0 0 0 1))')
        out.append(f'    (fill (color 255 255 255 0.0))')
        out.append(f'    (uuid {q(uid())})')
        out.append(f'    (property "Sheetname" {q(name)} (at {sx} {snap(sy - 3)} 0)')
        out.append(f'      (effects (font (size 1.27 1.27))))')
        out.append(f'    (property "Sheetfile" {q(fname)} (at {sx} {snap(sy + sheet_h + 2)} 0)')
        out.append(f'      (effects (font (size 1.27 1.27))))')
        out.append('  )')
        out.append('')

    # Sheet instances
    out.append('  (sheet_instances')
    out.append('    (path "/"')
    out.append('      (page "1")))')
    out.append('')
    out.append(')')

    return '\n'.join(out)


def build_sub_sheet(sheet_name, components, nets, db, page_num=1):
    """Build a sub-sheet schematic containing only the given components.

    Reuses the existing build_schematic logic but filtered to sheet components.
    """
    # Filter nets to only include members present in this sheet
    sheet_refs = {c["ref"] for c in components}
    filtered_nets = {}
    for net_name, members in nets.items():
        filtered = [m for m in members if m["ref"] in sheet_refs]
        if filtered:
            filtered_nets[net_name] = filtered

    # Build the schematic for this subset
    content, unresolved = build_schematic(components, filtered_nets, db,
                                          paper="A4", page_num=page_num)
    return content, unresolved


# ═══ Main assembly ═══════════════════════════════════════════════════════════

def build_schematic(components, nets, db, paper="A3", page_num=1):
    c_map = {c["ref"]: c for c in components}

    # Group and layout
    groups = group_components(components, nets)
    positions = layout(groups, components, nets, db)

    # Build pin lookups for each symbol
    all_syms = set()
    pwr_syms = set()
    pin_data = {}      # kicad_symbol -> {pin_num: pin_dict}
    synth_blocks = {}  # kicad_symbol -> block_str (for missing lib symbols)

    for c in components:
        cid = c.get("component_id", "")
        comp_entry = db.get(cid, {})
        sym = comp_entry.get("kicad_symbol", "")
        if sym:
            all_syms.add(sym)
            pins = get_sym_pins(sym)
            if pins:
                pin_data[sym] = pins
            elif sym not in pin_data:
                # Symbol not found in KiCad library — generate synthetic
                pm = _gather_db_pins(comp_entry)
                # Include any netlist pads not already in the component DB
                for net_members in nets.values():
                    for m in net_members:
                        if m["ref"] == c["ref"]:
                            ps = str(m["pad"])
                            if ps not in pm:
                                pm[ps] = f"P{ps}"
                if pm:
                    block, pdata = _synth_symbol_block(sym, pm)
                    synth_blocks[sym] = block
                    pin_data[sym] = pdata

    for net in nets:
        if is_power_net(net):
            pwr_syms.add(power_lib_id(net))

    # Build output
    root_uuid = uid()
    out = []
    out.append('(kicad_sch')
    out.append('  (version 20250114)')
    out.append('  (generator "eisla")')
    out.append('  (generator_version "9.0")')
    out.append(f'  (uuid {q(root_uuid)})')
    out.append(f'  (paper {q(paper)})')
    out.append('')

    # lib_symbols
    ls = build_lib_symbols(all_syms | pwr_syms, synth_blocks)
    if ls:
        out.append(ls)
        out.append('')

    # Component instances
    for c in components:
        ref = c["ref"]
        cid = c.get("component_id", "")
        comp = db.get(cid, {})
        sym = comp.get("kicad_symbol", "Device:Module")
        sx, sy, rot = positions.get(ref, (100, 100, 0))
        pins = pin_data.get(sym, {})
        pnums = sorted(pins.keys())
        sym_uuid = uid()
        out.append(fmt_sym(ref, comp, sx, sy, rot, pnums, pins, sym_uuid, root_uuid))

    out.append('')

    # Power symbols and labels at pin endpoints
    pwr_idx = 0
    placed_items = []       # [(x, y)] for overlap detection
    unresolved = []
    LABEL_OFFSET = 10.16    # 4 grid steps — clears pin name text
    MIN_GAP = 5.08          # minimum distance between placed items (2 grid steps)

    # Lane counters for nudged labels — each nudged label gets its own vertical
    # wire lane PAST the label column so vertical wires never cross other labels'
    # horizontal wire endpoints (which would create unintended KiCad junctions).
    right_lane_idx = 0
    left_lane_idx = 0

    def is_crowded(x, y):
        return any(abs(ix - x) < MIN_GAP and abs(iy - y) < MIN_GAP
                   for ix, iy in placed_items)

    for net, members in nets.items():
        for m in members:
            ref, pad = m["ref"], str(m["pad"])
            if ref not in positions:
                continue
            sx, sy, rot = positions[ref]
            cid = c_map.get(ref, {}).get("component_id", "")
            sym = db.get(cid, {}).get("kicad_symbol", "")
            pins = pin_data.get(sym, {})
            pin = pins.get(pad)

            if not pin:
                unresolved.append(f"{ref}.{pad} ({net})")
                continue

            px, py = pin_pos(pin, sx, sy, rot)

            if is_power_net(net):
                # Place power symbol directly at pin endpoint;
                # only add a short vertical wire if nudged for collision
                ppx, ppy = px, py
                nudge_dir = GRID if "GND" in net else -GRID
                while is_crowded(ppx, ppy):
                    ppy = snap(ppy + nudge_dir)
                placed_items.append((ppx, ppy))
                pwr_idx += 1
                pwr_uuid = uid()
                # Vertical wire only when nudged from original position
                if abs(ppy - py) > 0.01:
                    out.append(fmt_wire(px, py, ppx, ppy))
                out.append(fmt_pwr(net, ppx, ppy, pwr_idx, pwr_uuid, root_uuid))
            else:
                # Offset label away from symbol via a short horizontal wire
                if px < sx:
                    lrot = 180   # left-facing label, connection on right
                    lpx = snap(px - LABEL_OFFSET)
                else:
                    lrot = 0     # right-facing label, connection on left
                    lpx = snap(px + LABEL_OFFSET)
                lpy = py
                # Avoid stacking: nudge vertically if crowded
                while is_crowded(lpx, lpy):
                    lpy = snap(lpy + GRID * 2)
                placed_items.append((lpx, lpy))
                # Route wire from pin to label
                if abs(lpy - py) > 0.01:
                    # Nudged label — route via unique vertical lane PAST the
                    # label column.  Each lane is at a different x so vertical
                    # wires never share x with each other or with non-nudged
                    # horizontal wire endpoints at lpx.  KiCad only creates
                    # junctions at endpoint-on-wire, not midpoint crossings.
                    if px >= sx:  # right side — lanes extend rightward
                        lane_x = snap(lpx + (right_lane_idx + 1) * GRID)
                        right_lane_idx += 1
                    else:         # left side — lanes extend leftward
                        lane_x = snap(lpx - (left_lane_idx + 1) * GRID)
                        left_lane_idx += 1
                    out.append(fmt_wire(px, py, lane_x, py))
                    out.append(fmt_wire(lane_x, py, lane_x, lpy))
                    out.append(fmt_wire(lane_x, lpy, lpx, lpy))
                else:
                    out.append(fmt_wire(px, py, lpx, lpy))
                out.append(fmt_label(net, lpx, lpy, lrot))

    # No-connect flags on unused pins
    # Build set of (ref, pad) that are connected to a net
    connected = set()
    for net, members in nets.items():
        for m in members:
            connected.add((m["ref"], str(m["pad"])))

    for c in components:
        ref = c["ref"]
        if ref not in positions:
            continue
        sx, sy, rot = positions[ref]
        cid = c.get("component_id", "")
        sym = db.get(cid, {}).get("kicad_symbol", "")
        pins = pin_data.get(sym, {})
        for pnum, pin in pins.items():
            if (ref, pnum) in connected:
                continue
            px, py = pin_pos(pin, sx, sy, rot)
            out.append(f'  (no_connect (at {px} {py}) (uuid {q(uid())}))')

    out.append('')
    out.append('  (sheet_instances')
    out.append('    (path "/"')
    out.append(f'      (page {q(str(page_num))})))')
    out.append('')
    out.append(')')

    return '\n'.join(out), unresolved


# ═══ Support passive auto-addition ══════════════════════════════════════════

def add_support_passives(comp_list, nets, db):
    """Auto-add support passives for dead-end nets.

    Adds pull-up resistors for MCU boot pins, and support components for
    buck regulators (inductor, bootstrap cap, feedback divider, I/O caps).
    Modifies comp_list and nets in-place.
    Returns list of descriptions for logging.
    """
    added_log = []
    ref_counter = {}

    for c in comp_list:
        m = re.match(r'^([A-Z]+)(\d+)$', c.get("ref", ""))
        if m:
            p, n = m.group(1), int(m.group(2))
            ref_counter[p] = max(ref_counter.get(p, 0), n)

    def next_ref(cid):
        if cid.startswith("res_"):
            pfx = "R"
        elif cid.startswith("cap_"):
            pfx = "C"
        elif cid.startswith("inductor_"):
            pfx = "L"
        elif cid.startswith("diode_"):
            pfx = "D"
        else:
            pfx = "U"
        ref_counter[pfx] = ref_counter.get(pfx, 0) + 1
        return f"{pfx}{ref_counter[pfx]}"

    def add_comp(cid, reason):
        if cid not in db:
            return None
        ref = next_ref(cid)
        comp_list.append({
            "component_id": cid, "ref": ref,
            "auto_added": True, "schematic_auto_added": True,
            "reason": reason,
        })
        added_log.append(f"{ref} ({db[cid].get('display_name', cid)}) -- {reason}")
        return ref

    def add_to_net(net, ref, pad):
        nets.setdefault(net, []).append({"ref": ref, "pad": str(pad)})

    def remove_from_net(net, ref, pad):
        if net in nets:
            nets[net] = [ep for ep in nets[net]
                         if not (ep["ref"] == ref and str(ep["pad"]) == str(pad))]

    # ── 1. MCU boot-pin pull-ups ─────────────────────────────────────────
    for c in comp_list:
        cid = c.get("component_id", "")
        comp = db.get(cid, {})
        if comp.get("category") != "mcu":
            continue
        mcu_ref = c["ref"]
        for net_name in sorted(nets):
            if not net_name.startswith("CTRL_"):
                continue
            eps = nets[net_name]
            if len(eps) != 1 or eps[0]["ref"] != mcu_ref:
                continue
            tag = net_name[len("CTRL_"):]
            if tag not in ("EN", "IO0", "IO2"):
                continue
            ref = add_comp("res_10k_0402", f"Pull-up for {mcu_ref} {tag}")
            if ref:
                add_to_net(net_name, ref, "1")
                add_to_net("VCC_3V3", ref, "2")

    # ── 2. Buck regulator support ────────────────────────────────────────
    for c in list(comp_list):
        cid = c.get("component_id", "")
        comp = db.get(cid, {})
        if comp.get("subcategory") != "buck_converter":
            continue
        reg_ref = c["ref"]
        output_data = comp.get("pins", {}).get("output", {})

        # Find SW pad and its current net
        sw_pad = None
        for key, val in output_data.items():
            if key not in ("net", "note"):
                sw_pad = str(val)
                break
        sw_net = None
        if sw_pad:
            for nn, eps in nets.items():
                if any(ep["ref"] == reg_ref and str(ep["pad"]) == sw_pad for ep in eps):
                    sw_net = nn
                    break

        # a) Inductor: split SW off into its own net, inductor bridges to output
        sw_int_net = f"SW_{reg_ref}"
        if sw_pad and sw_net:
            remove_from_net(sw_net, reg_ref, sw_pad)
            add_to_net(sw_int_net, reg_ref, sw_pad)
            ref = add_comp("inductor_10uh", f"Buck inductor for {reg_ref}")
            if ref:
                add_to_net(sw_int_net, ref, "1")
                add_to_net(sw_net, ref, "2")

        # b) Bootstrap cap: BST to SW
        bst_net = f"BST_{reg_ref}"
        if bst_net in nets and len(nets[bst_net]) == 1:
            ref = add_comp("cap_100nf_bst", f"Bootstrap cap for {reg_ref}")
            if ref:
                add_to_net(bst_net, ref, "1")
                add_to_net(sw_int_net, ref, "2")

        # c) Feedback resistor divider: output → Rtop → FB → Rbot → GND
        fb_net = f"FB_{reg_ref}"
        if fb_net in nets and len(nets[fb_net]) == 1:
            out_net = sw_net or "VCC_3V3"
            ref_top = add_comp("res_100k_0402", f"FB divider top for {reg_ref}")
            if ref_top:
                add_to_net(out_net, ref_top, "1")
                add_to_net(fb_net, ref_top, "2")
            ref_bot = add_comp("res_49k9_0402", f"FB divider bottom for {reg_ref}")
            if ref_bot:
                add_to_net(fb_net, ref_bot, "1")
                add_to_net("GND", ref_bot, "2")

        # d) Input cap: VIN to GND
        vin_net = None
        for pw in comp.get("pins", {}).get("power", []):
            net_tag = pw.get("net", "")
            if net_tag.upper() == "GND":
                continue
            pads = pw.get("pins", [])
            if not pads and "pin" in pw:
                pads = [pw["pin"]]
            for p in pads:
                for nn2, eps2 in nets.items():
                    if any(ep["ref"] == reg_ref and str(ep["pad"]) == str(p) for ep in eps2):
                        vin_net = nn2
                        break
                if vin_net:
                    break
            if vin_net:
                break
        if vin_net:
            ref = add_comp("cap_10uf_0805", f"Input cap for {reg_ref}")
            if ref:
                add_to_net(vin_net, ref, "1")
                add_to_net("GND", ref, "2")

        # e) Output cap: VOUT to GND
        if sw_net:
            ref = add_comp("cap_10uf_0805", f"Output cap for {reg_ref}")
            if ref:
                add_to_net(sw_net, ref, "1")
                add_to_net("GND", ref, "2")

    return added_log


# ═══ Main ═════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage: python schematic.py <job_dir>")
        sys.exit(1)

    from refdes import assign_refs
    from netlist import build_netlist, classify_nets

    job_dir  = Path(sys.argv[1])
    db       = load_json(COMPONENTS_PATH)
    resolved = load_json(job_dir / "resolved.json")

    if not db:
        print("ERROR: components.json not found")
        sys.exit(1)
    if not resolved:
        print(f"ERROR: resolved.json not found in {job_dir}")
        sys.exit(1)

    # Strip only schematic-stage auto-adds (idempotent re-runs).
    # Keep resolver auto-adds (generic_role set) — those are real design components.
    base_components = [c for c in resolved["resolved_components"]
                       if not c.get("schematic_auto_added")]

    # 1. Assign reference designators
    comp_list = assign_refs(base_components, db)

    # 2. Generate netlist
    nets, engineer_review = build_netlist(resolved, comp_list, db)

    # 2.5. Auto-add support passives (pull-ups, buck regulator support)
    support_added = add_support_passives(comp_list, nets, db)
    if support_added:
        print(f"[schematic] Auto-added {len(support_added)} support passive(s):")
        for s in support_added:
            safe = s.encode("ascii", errors="replace").decode("ascii")
            print(f"  + {safe}")

    # 3. Write netlist.json (consumed by placement + PCB stages)
    netlist_out = {
        "nets":            nets,
        "net_count":       len(nets),
        "engineer_review": engineer_review,
    }
    nl_path = job_dir / "netlist.json"
    with open(nl_path, "w", encoding="utf-8") as f:
        json.dump(netlist_out, f, indent=2)

    # 3.5 Write net_classes.json (consumed by kicad_pcb + drc stages)
    nc = classify_nets(nets)
    nc_path = job_dir / "net_classes.json"
    with open(nc_path, "w", encoding="utf-8") as f:
        json.dump(nc, f, indent=2)
    class_counts = {}
    for cls in nc.get("assignments", {}).values():
        class_counts[cls] = class_counts.get(cls, 0) + 1
    print(f"[schematic] Net classes: "
          + ", ".join(f"{k}={v}" for k, v in sorted(class_counts.items())))

    # Write updated component list to resolved.json for downstream stages
    resolved["resolved_components"] = [
        {k: v for k, v in c.items() if k != "ref"}
        for c in comp_list
    ]
    with open(job_dir / "resolved.json", "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2)

    # 4. Build schematic — hierarchical if enough components, flat otherwise
    sheets = assign_sheets(comp_list, nets, db)
    all_unresolved = []

    if len(sheets) > 1:
        # Hierarchical: root sheet + sub-sheets
        root_content = build_root_sheet(sheets, db)
        out_path = job_dir / "board.kicad_sch"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(root_content)
        print(f"[schematic] Root sheet with {len(sheets)} sub-sheets")

        for i, (sheet_name, sheet_comps) in enumerate(sheets, start=1):
            sub_content, sub_unresolved = build_sub_sheet(
                sheet_name, sheet_comps, nets, db, page_num=i + 1
            )
            all_unresolved.extend(sub_unresolved)
            fname = _slugify(sheet_name) + ".kicad_sch"
            sub_path = job_dir / fname
            with open(sub_path, "w", encoding="utf-8") as f:
                f.write(sub_content)
            print(f"[schematic]   Sheet {i}: {sheet_name} ({len(sheet_comps)} components) -> {fname}")
    else:
        # Flat: single sheet (small designs)
        content, all_unresolved = build_schematic(comp_list, nets, db)
        out_path = job_dir / "board.kicad_sch"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

    nc = len(comp_list)
    nn = len(nets)
    print(f"[schematic] Generated: {nc} symbols, {nn} nets")
    if all_unresolved:
        print(f"[schematic] {len(all_unresolved)} pin(s) not found in symbol library:")
        for u in all_unresolved[:10]:
            print(f"  - {u}")
    print(f"[schematic] Saved to {job_dir / 'board.kicad_sch'}")


if __name__ == "__main__":
    main()
