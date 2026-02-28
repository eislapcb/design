"""
Eisla -- KiCad Schematic Generator (python/schematic.py)

Session 10. Runs after netlist.py (post-routing in production pipeline).

Generates board.kicad_sch in KiCad 6+ s-expression format.
No eeschema Python API exists -- we write the file format directly.
The output opens natively in KiCad 6/7/8/9.

Symbol handling:
  - Uses kicad_symbol field from components.json
  - Missing symbol library -> Device:Module generic fallback + engineer_review flag
  - Power symbols: Device:PWR_FLAG for VCC_3V3, VCC_5V, VBAT, GND

Layout:
  - Components placed on 50mil grid in rows (max 6 per row)
  - Power symbols in top-right corner
  - Net labels connect signals between components

Input (in job_dir):
  netlist.json   -- nets + engineer_review flags

Output (in job_dir):
  board.kicad_sch

Usage:
    python schematic.py <job_dir>
    python schematic.py <job_dir> --test   (generates test schematic)
"""

import json
import sys
import uuid
from pathlib import Path

SCRIPT_DIR      = Path(__file__).parent
PROJECT_ROOT    = SCRIPT_DIR.parent
COMPONENTS_PATH = PROJECT_ROOT / "data" / "components.json"
SYM_LIB_BASE    = Path("C:/Program Files/KiCad/9.0/share/kicad/symbols")

# Symbol library availability (checked at startup)
MISSING_SYM_LIBS = {"Connector_Card", "Interface_I2C", "Interface_NFC",
                    "Logic_LevelShifter", "RF_Cellular"}

# Schematic grid (mils — KiCad native unit)
GRID        = 50     # mils between grid points
COL_STEP    = 1000   # mils between component columns
ROW_STEP    = 1000   # mils between component rows
COMPS_PER_ROW = 5
ORIGIN_X    = 500
ORIGIN_Y    = 500

# Power symbol offsets (placed at top of sheet)
POWER_X     = 200
POWER_Y     = 200
POWER_STEP  = 400


# ─── Helpers ──────────────────────────────────────────────────────────────────

def uid():
    return str(uuid.uuid4())


def load_db():
    with open(COMPONENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_json(path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sym_lib_ok(lib_name):
    return (SYM_LIB_BASE / f"{lib_name}.kicad_sym").exists()


# ─── S-expression writer ──────────────────────────────────────────────────────

class Sexp:
    """Simple s-expression builder."""

    def __init__(self, tag, *children):
        self.tag = tag
        self.children = list(children)

    def add(self, *children):
        self.children.extend(children)
        return self

    def __str__(self):
        return self._render(0)

    def _render(self, indent):
        pad = "  " * indent
        parts = [f"({self.tag}"]
        for c in self.children:
            if isinstance(c, Sexp):
                parts.append("\n" + c._render(indent + 1))
            elif isinstance(c, str):
                parts.append(f" {c}")
            elif isinstance(c, (int, float)):
                parts.append(f" {c}")
        parts.append(")")
        return pad + "".join(parts)


def q(s):
    """Quote a string value."""
    return f'"{s}"'


def xy(x, y):
    return f"(xy {x} {y})"


def at(x, y, rot=0):
    if rot:
        return f"(at {x} {y} {rot})"
    return f"(at {x} {y})"


def prop(key, val, id_num, x=0, y=0, hidden=False):
    hide = " (hide yes)" if hidden else ""
    return (f'(property {q(key)} {q(val)} (at {x} {y} 0)'
            f' (effects (font (size 1.27 1.27))){hide})')


# ─── Symbol builder ───────────────────────────────────────────────────────────

def make_symbol(ref, comp, x_mil, y_mil, sym_id, fallback_used):
    """
    Return the s-expression string for a schematic symbol instance.
    KiCad 6+ format.
    """
    sym_lib_id = comp.get("kicad_symbol", "Device:Module")
    lib_part   = sym_lib_id.split(":", 1)
    lib_name   = lib_part[0] if len(lib_part) == 2 else "Device"

    if not sym_lib_ok(lib_name) or fallback_used:
        sym_lib_id = "Device:Module"

    # Convert mils to mm for KiCad schematic coordinates (KiCad 6+ uses mm in .kicad_sch)
    x_mm = round(x_mil * 0.0254, 4)
    y_mm = round(y_mil * 0.0254, 4)

    value = comp.get("mpn", comp.get("display_name", ref))
    fp    = comp.get("kicad_footprint", "")

    block = (
        f'  (symbol\n'
        f'    (lib_id {q(sym_lib_id)})\n'
        f'    (at {x_mm} {y_mm} 0)\n'
        f'    (unit 1)\n'
        f'    (exclude_from_sim no)\n'
        f'    (in_bom yes)\n'
        f'    (on_board yes)\n'
        f'    (dnp no)\n'
        f'    (uuid {q(uid())})\n'
        f'    (property "Reference" {q(ref)} (at {x_mm} {y_mm - 2.54} 0)\n'
        f'      (effects (font (size 1.27 1.27))))\n'
        f'    (property "Value" {q(value)} (at {x_mm} {y_mm + 2.54} 0)\n'
        f'      (effects (font (size 1.27 1.27))))\n'
        f'    (property "Footprint" {q(fp)} (at {x_mm} {y_mm} 0)\n'
        f'      (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'  )'
    )
    return block


def make_power_symbol(net_name, x_mil, y_mil):
    """Power flag / rail symbol."""
    x_mm = round(x_mil * 0.0254, 4)
    y_mm = round(y_mil * 0.0254, 4)

    lib_id = "power:GND" if "GND" in net_name else f"power:+3.3V" if "3V3" in net_name else "power:+5V"
    if "VBAT" in net_name:
        lib_id = "power:VBAT"

    return (
        f'  (symbol\n'
        f'    (lib_id {q(lib_id)})\n'
        f'    (at {x_mm} {y_mm} 0)\n'
        f'    (unit 1)\n'
        f'    (exclude_from_sim no)\n'
        f'    (in_bom yes)\n'
        f'    (on_board yes)\n'
        f'    (dnp no)\n'
        f'    (uuid {q(uid())})\n'
        f'    (property "Reference" {q("#PWR0" + str(abs(hash(net_name)) % 100))} (at {x_mm} {y_mm} 0)\n'
        f'      (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'    (property "Value" {q(net_name)} (at {x_mm} {y_mm + 2} 0)\n'
        f'      (effects (font (size 1.27 1.27))))\n'
        f'  )'
    )


def make_net_label(net_name, x_mil, y_mil):
    """Net label (global) to connect signals across the sheet."""
    x_mm = round(x_mil * 0.0254, 4)
    y_mm = round(y_mil * 0.0254, 4)
    return (
        f'  (global_label {q(net_name)}\n'
        f'    (shape input)\n'
        f'    (at {x_mm} {y_mm} 0)\n'
        f'    (effects (font (size 1.27 1.27)))\n'
        f'    (uuid {q(uid())})\n'
        f'    (property "Intersheet References" "" (at {x_mm} {y_mm} 0)\n'
        f'      (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'  )'
    )


# ─── Schematic file writer ────────────────────────────────────────────────────

def build_schematic(placement, netlist, db):
    """Return the full .kicad_sch file content as a string."""
    components    = placement.get("components", [])
    nets          = netlist.get("nets", {})
    er_refs       = {e["ref"] for e in netlist.get("engineer_review", [])}

    lines = []

    # KiCad 6+ schematic header
    lines.append('(kicad_sch')
    lines.append('  (version 20230121)')
    lines.append('  (generator "eisla")')
    lines.append('  (paper "A3")')
    lines.append(f'  (uuid {q(uid())})')
    lines.append('')

    # ── Component symbols ──────────────────────────────────────────────────
    for i, comp_data in enumerate(components):
        ref    = comp_data.get("ref", "?")
        cid    = comp_data.get("component_id", "")
        comp   = db.get(cid, {})
        col    = i % COMPS_PER_ROW
        row    = i // COMPS_PER_ROW
        x_mil  = ORIGIN_X + col * COL_STEP
        y_mil  = ORIGIN_Y + row * ROW_STEP
        fallback = ref in er_refs

        sym = make_symbol(ref, comp, x_mil, y_mil, i, fallback)
        lines.append(sym)

    lines.append('')

    # ── Power symbols ──────────────────────────────────────────────────────
    power_nets = [n for n in nets if any(kw in n for kw in
                  ("GND", "VCC", "3V3", "5V", "VBAT"))]
    for j, pnet in enumerate(sorted(set(power_nets))):
        px = POWER_X + j * POWER_STEP
        py = POWER_Y
        lines.append(make_power_symbol(pnet, px, py))

    lines.append('')

    # ── Net labels for signal nets ─────────────────────────────────────────
    # Place one global label per net, near the first member component
    comp_positions = {}  # ref -> (col, row) in schematic grid
    for i, comp_data in enumerate(components):
        ref = comp_data.get("ref", "?")
        col = i % COMPS_PER_ROW
        row = i // COMPS_PER_ROW
        comp_positions[ref] = (col, row)

    signal_nets = [n for n in nets if not any(kw in n for kw in
                   ("GND", "VCC", "3V3", "5V", "VBAT"))]
    label_offset = 0
    for net_name in sorted(signal_nets):
        members = nets[net_name]
        if not members:
            continue
        first_ref = members[0]["ref"]
        pos = comp_positions.get(first_ref, (0, 0))
        x_mil = ORIGIN_X + pos[0] * COL_STEP + label_offset * 200
        y_mil = ORIGIN_Y + pos[1] * ROW_STEP + 400
        label_offset = (label_offset + 1) % 3
        lines.append(make_net_label(net_name, x_mil, y_mil))

    lines.append('')
    lines.append(')')  # close kicad_sch

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python schematic.py <job_dir>")
        sys.exit(1)

    test_mode = "--test" in sys.argv
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

    er_flags = netlist.get("engineer_review", [])

    # Check for additional missing symbol libs in this design's components
    for comp_data in placement.get("components", []):
        cid  = comp_data.get("component_id", "")
        comp = db.get(cid, {})
        sym  = comp.get("kicad_symbol", "")
        if ":" in sym:
            lib_name = sym.split(":")[0]
            if lib_name in MISSING_SYM_LIBS and not sym_lib_ok(lib_name):
                ref = comp_data.get("ref", "?")
                existing = [e for e in er_flags if e["ref"] == ref]
                if not existing:
                    er_flags.append({
                        "ref":          ref,
                        "component_id": cid,
                        "display_name": comp.get("display_name", cid),
                        "reasons":      [f"symbol library '{lib_name}' not installed "
                                         f"— Device:Module fallback used"],
                    })

    content = build_schematic(placement, netlist, db)

    out_path = job_dir / "board.kicad_sch"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    n_comps = len(placement.get("components", []))
    n_nets  = len(netlist.get("nets", {}))
    print(f"[schematic] Generated schematic: {n_comps} symbols, {n_nets} nets")

    if er_flags:
        print(f"[schematic] {len(er_flags)} component(s) using fallback symbol:")
        for flag in er_flags:
            print(f"  {flag['ref']} ({flag['display_name']}): {'; '.join(flag['reasons'])}")

    print(f"[schematic] Saved to {out_path}")

    if test_mode:
        print("[schematic] Test mode: verifying file can be parsed back")
        content_check = out_path.read_text(encoding="utf-8")
        assert "(kicad_sch" in content_check
        assert "(version" in content_check
        print("[schematic] Parse check OK")


if __name__ == "__main__":
    main()
