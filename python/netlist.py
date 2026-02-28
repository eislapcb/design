"""
Eisla -- Netlist Generator (python/netlist.py)

Session 10. Runs after placement.py, before kicad_pcb.py.

Derives a logical netlist from:
  - resolved.json   (component IDs + quantities)
  - placement.json  (ref designators + positions)
  - components.json (pins.power + pins.interfaces)

Net naming conventions:
  GND, VCC_5V, VCC_3V3, VBAT, VBAT_COIN
  I2C_SDA, I2C_SCL
  SPI_MOSI, SPI_MISO, SPI_SCK, SPI_CS_1 ... SPI_CS_n
  UART1_TX, UART1_RX, UART2_TX, UART2_RX
  USB_DP, USB_DM
  CAN_H, CAN_L

Output format (netlist.json):
{
  "nets": {
    "GND":      [{"ref": "U1", "pad": "13"}, ...],
    "VCC_3V3":  [...],
    "I2C_SDA":  [...],
    ...
  },
  "engineer_review": [
    {"ref": "U3", "component_id": "...", "reason": "..."}
  ]
}

Usage:
    python netlist.py <job_dir>
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR      = Path(__file__).parent
PROJECT_ROOT    = SCRIPT_DIR.parent
COMPONENTS_PATH = PROJECT_ROOT / "data" / "components.json"

# Missing symbol/footprint libs that require engineer review
MISSING_FP_LIBS  = {"RF_Cellular"}
MISSING_SYM_LIBS = {"Connector_Card", "Interface_I2C", "Interface_NFC",
                    "Logic_LevelShifter", "RF_Cellular"}


def load_db():
    with open(COMPONENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_json(path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── Net name helpers ─────────────────────────────────────────────────────────

def power_net_name(raw_net):
    """Normalise raw net names from pins.power to canonical net names."""
    mapping = {
        "GND": "GND", "AGND": "GND", "PGND": "GND", "VSS": "GND",
        "3V3": "VCC_3V3", "VCC_3V3": "VCC_3V3", "VDD_3V3": "VCC_3V3",
        "5V": "VCC_5V", "VCC_5V": "VCC_5V", "VIN": "VCC_5V", "VUSB": "VCC_5V",
        "VBAT": "VBAT", "VBAT_COIN": "VBAT_COIN",
        "VOUT": None,  # LDO output — handled separately
    }
    return mapping.get(raw_net, raw_net)


def ldo_output_net(pins_data):
    """Return the net name for an LDO output (e.g. 3V3 from AMS1117)."""
    out = pins_data.get("output", {})
    raw = out.get("net", "")
    return power_net_name(raw) or "VCC_3V3"


# ─── Main netlist builder ─────────────────────────────────────────────────────

def build_netlist(resolved, placement, db):
    """
    Build a dict:  net_name -> list of {ref, pad}
    Also returns engineer_review list for flagged components.
    """
    nets              = {}   # net_name -> [{ref, pad}]
    engineer_review   = []
    spi_cs_counter    = [0]  # mutable for closure
    uart_counter      = [0]

    def add(net_name, ref, pad):
        if net_name not in nets:
            nets[net_name] = []
        entry = {"ref": ref, "pad": str(pad)}
        if entry not in nets[net_name]:
            nets[net_name].append(entry)

    # Build lookup: component_id -> ref from placement
    placement_comps = placement.get("components", [])
    comp_ref = {}   # component_id -> list of refs (multiple instances)
    for pc in placement_comps:
        cid = pc.get("component_id", "")
        ref = pc.get("ref", "")
        comp_ref.setdefault(cid, []).append(ref)

    # Resolved components list (may have multiple of same component_id)
    resolved_list = resolved.get("resolved_components", [])

    # Assign an instance index when multiple of the same component exist
    instance_idx = {}  # component_id -> counter

    for rc in resolved_list:
        cid = rc.get("component_id", "")
        comp = db.get(cid, {})
        if not comp:
            continue

        idx = instance_idx.get(cid, 0)
        instance_idx[cid] = idx + 1

        refs_for_cid = comp_ref.get(cid, [])
        if not refs_for_cid:
            continue
        # Use instance index to pick the right ref if multiple
        ref = refs_for_cid[min(idx, len(refs_for_cid) - 1)]

        pins = comp.get("pins", {})

        # ── Engineer review check ──────────────────────────────────────────
        fp  = comp.get("kicad_footprint", "")
        sym = comp.get("kicad_symbol", "")
        fp_lib  = fp.split(":")[0]  if ":" in fp  else ""
        sym_lib = sym.split(":")[0] if ":" in sym else ""
        reasons = []
        if fp_lib  in MISSING_FP_LIBS:  reasons.append(f"footprint library '{fp_lib}' not installed")
        if sym_lib in MISSING_SYM_LIBS: reasons.append(f"symbol library '{sym_lib}' not installed")
        if not fp:  reasons.append("kicad_footprint missing from component database")
        if reasons:
            engineer_review.append({
                "ref":          ref,
                "component_id": cid,
                "display_name": comp.get("display_name", cid),
                "reasons":      reasons,
            })

        # ── Power pins ────────────────────────────────────────────────────
        for pw in pins.get("power", []):
            raw_net = pw.get("net", "")
            net = power_net_name(raw_net)
            if net is None:
                net = ldo_output_net(pins)
            for pad in pw.get("pins", []):
                add(net, ref, pad)

        # LDO output pad
        out = pins.get("output", {})
        if out and out.get("net"):
            out_net = power_net_name(out["net"]) or ldo_output_net(pins)
            out_pad = out.get("VOUT") or out.get("vout")
            if out_pad:
                add(out_net, ref, out_pad)

        # ── Interface pins ────────────────────────────────────────────────
        ifaces = pins.get("interfaces", {})

        # I2C — shared bus
        if "I2C" in ifaces:
            i2c = ifaces["I2C"]
            if "SDA" in i2c:
                add("I2C_SDA", ref, i2c["SDA"])
            if "SCL" in i2c:
                add("I2C_SCL", ref, i2c["SCL"])

        # SPI — shared MOSI/MISO/SCK, individual CS per peripheral
        if "SPI" in ifaces:
            spi = ifaces["SPI"]
            if "MOSI" in spi:
                add("SPI_MOSI", ref, spi["MOSI"])
            if "MISO" in spi:
                add("SPI_MISO", ref, spi["MISO"])
            if "SCK" in spi:
                add("SPI_SCK", ref, spi["SCK"])
            if "CS" in spi:
                # MCU has multiple CS lines; peripherals each get their own
                if comp.get("category") == "mcu":
                    # MCU side — we'll number these per connected peripheral later
                    add("SPI_CS_1", ref, spi["CS"])
                else:
                    spi_cs_counter[0] += 1
                    cs_net = f"SPI_CS_{spi_cs_counter[0]}"
                    add(cs_net, ref, spi["CS"])

        # UART
        if "UART" in ifaces:
            uart = ifaces["UART"]
            uart_counter[0] += 1
            n = uart_counter[0]
            if "TX" in uart:
                # TX of this device connects to RX of the other — label from device perspective
                add(f"UART{n}_TX", ref, uart["TX"])
            if "RX" in uart:
                add(f"UART{n}_RX", ref, uart["RX"])

        # USB
        if "USB" in ifaces:
            usb = ifaces["USB"]
            if "DP" in usb:
                add("USB_DP", ref, usb["DP"])
            if "DM" in usb:
                add("USB_DM", ref, usb["DM"])
            if "D+" in usb:
                add("USB_DP", ref, usb["D+"])
            if "D-" in usb:
                add("USB_DM", ref, usb["D-"])

        # CAN
        if "CAN" in ifaces:
            can = ifaces["CAN"]
            if "CANH" in can:
                add("CAN_H", ref, can["CANH"])
            if "CANL" in can:
                add("CAN_L", ref, can["CANL"])

        # 1-Wire
        if "1-Wire" in ifaces or "OneWire" in ifaces:
            ow = ifaces.get("1-Wire") or ifaces.get("OneWire", {})
            if "DQ" in ow:
                add("ONEWIRE_DQ", ref, ow["DQ"])

        # INT / IRQ / RST — individual signal nets per peripheral
        for sig_key, net_prefix in [("INT", "INT"), ("IRQ", "INT"), ("RST", "RST"), ("RESET", "RST")]:
            for iface_data in ifaces.values():
                if sig_key in iface_data:
                    add(f"{net_prefix}_{ref}", ref, iface_data[sig_key])

    return nets, engineer_review


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python netlist.py <job_dir>")
        sys.exit(1)

    job_dir  = Path(sys.argv[1])
    db       = load_db()
    resolved = load_json(job_dir / "resolved.json")
    placement = load_json(job_dir / "placement.json")

    if not resolved:
        print(f"ERROR: resolved.json not found in {job_dir}")
        sys.exit(1)
    if not placement:
        print(f"ERROR: placement.json not found in {job_dir}")
        sys.exit(1)

    nets, engineer_review = build_netlist(resolved, placement, db)

    result = {
        "nets":            nets,
        "net_count":       len(nets),
        "engineer_review": engineer_review,
    }

    out_path = job_dir / "netlist.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"[netlist] Generated {len(nets)} nets for "
          f"{len(placement.get('components', []))} components")
    if engineer_review:
        print(f"[netlist] {len(engineer_review)} component(s) flagged for engineer review:")
        for flag in engineer_review:
            print(f"  {flag['ref']} ({flag['display_name']}): {'; '.join(flag['reasons'])}")
    print(f"[netlist] Saved to {out_path}")


if __name__ == "__main__":
    main()
