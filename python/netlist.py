"""
Eisla -- Netlist Generator (python/netlist.py)

Session 10. Runs after schematic.py, before placement.py.

Derives a logical netlist from:
  - resolved.json   (component IDs + quantities)
  - components.json (pins.power + pins.interfaces)

Reference designators are assigned via refdes.assign_refs().

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


# ─── Pad / net name helpers ───────────────────────────────────────────────────

def normalise_pad(pad_str):
    """Extract physical pad number from compound names like 'GPIO21/33' -> '33'."""
    if "/" in str(pad_str):
        return str(pad_str).rsplit("/", 1)[-1]
    return str(pad_str)

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


# ─── Interface key matching ──────────────────────────────────────────────────

SPI_BUS_PRIORITY = {
    "SPI": 0,       # Plain (ATmega, nRF)
    "SPI_VSPI": 1,  # ESP32 primary
    "SPI0": 1,      # RP2040 primary
    "SPI1": 2,      # RP2040 secondary
    "SPI_HSPI": 3,  # ESP32 secondary
}


def find_iface_keys(ifaces, prefix):
    """Find all interface keys matching a prefix.

    'SPI' matches 'SPI', 'SPI_VSPI', 'SPI0', 'SPI_HSPI', etc.
    'I2C' matches 'I2C', 'I2C0', 'I2C_1', etc.
    'UART' matches 'UART', 'UART0', 'UART2', etc.
    """
    matches = []
    for k in ifaces:
        if k == prefix:
            matches.append(k)
        elif k.startswith(prefix + "_"):
            matches.append(k)
        elif k.startswith(prefix) and len(k) > len(prefix) and k[len(prefix)].isdigit():
            matches.append(k)
    return matches


def pick_primary_bus(keys, priority):
    """Pick the highest-priority bus key from a list."""
    return min(keys, key=lambda k: priority.get(k, 99))


def get_power_pads(pw):
    """Get pad list from a power pin entry, handling both 'pins' (array) and 'pin' (scalar)."""
    pads = pw.get("pins", [])
    if not pads and "pin" in pw:
        pads = [pw["pin"]]
    return [str(p) for p in pads]


# ─── Main netlist builder ─────────────────────────────────────────────────────

def build_netlist(resolved, comp_list, db):
    """
    Build a dict:  net_name -> list of {ref, pad}
    Also returns engineer_review list for flagged components.

    Args:
        resolved: full resolved.json dict
        comp_list: list of {component_id, ref, ...} dicts (from refdes.assign_refs)
        db: components.json dict
    """
    nets              = {}   # net_name -> [{ref, pad}]
    engineer_review   = []
    spi_cs_counter    = [0]  # mutable for closure
    uart_counter      = [0]

    def add(net_name, ref, pad):
        if net_name not in nets:
            nets[net_name] = []
        entry = {"ref": ref, "pad": normalise_pad(pad)}
        if entry not in nets[net_name]:
            nets[net_name].append(entry)

    # Build lookup: component_id -> ref
    comp_ref = {}   # component_id -> list of refs (multiple instances)
    for pc in comp_list:
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
            for pad in get_power_pads(pw):
                add(net, ref, pad)

        # LDO / charger output pad
        out = pins.get("output", {})
        if out and out.get("net"):
            out_net = power_net_name(out["net"]) or ldo_output_net(pins)
            out_pad = None
            for key in ("VOUT", "vout", "BAT", "bat", "OUT", "out", "SW", "sw"):
                if key in out:
                    out_pad = str(out[key])
                    break
            if out_pad:
                add(out_net, ref, out_pad)

        # ── Control pins (TP4056 PROG/CHRG/STDBY, DW01A OD/OC, etc.) ────
        for ctrl in pins.get("control", []):
            ctrl_name = ctrl.get("name", "")
            ctrl_pin = ctrl.get("pin", "")
            if not ctrl_pin:
                continue
            config = ctrl.get("config", "")
            if config == "pull_up":
                supply_v = str(comp.get("supply_voltage", "5V"))
                pwr = "VCC_5V" if "5" in supply_v else "VCC_3V3"
                add(pwr, ref, ctrl_pin)
            elif ctrl_name:
                add(f"CTRL_{ctrl_name}", ref, ctrl_pin)

        # ── Connector terminals ────────────────────────────────────────
        for term in pins.get("terminals", []):
            term_net = term.get("net")
            if term_net:
                # Explicit net value (e.g. connector pins)
                mapped = power_net_name(term_net) or term_net
                for pad in term.get("pins", []):
                    add(mapped, ref, pad)
            else:
                # Discrete components (MOSFETs, etc.) — no explicit net.
                # Assign functional nets based on terminal name and role.
                tname = term.get("name", "").upper()
                satisfies = set(rc.get("satisfies", []))
                for pad in term.get("pins", []):
                    if tname == "S":
                        # Source pin: GND for N-FET, power rail for P-FET
                        cat = comp.get("category", "")
                        is_pmos = "p-mos" in cat.lower() or "p_mos" in cid.lower() or "ao3401" in cid.lower()
                        add("VCC_5V" if is_pmos else "GND", ref, pad)
                    elif tname == "G":
                        # Gate: driven by MCU GPIO → unique control net
                        add(f"CTRL_{ref}", ref, pad)
                    elif tname == "D":
                        # Drain: load side → unique output net
                        add(f"DRV_{ref}", ref, pad)
                    elif tname in ("A", "K"):
                        # Diode terminals
                        if tname == "K":
                            add("GND", ref, pad)
                        else:
                            add(f"CTRL_{ref}", ref, pad)

        # ── GPIO / misc pins (buck regulators, etc.) ──────────────────
        for gp in pins.get("gpio", []):
            gp_name = gp.get("name", "")
            gp_pin  = gp.get("pin", "")
            if not gp_pin:
                continue
            name_u = gp_name.upper()
            if name_u == "EN":
                # Enable pin — typically pulled up to input rail
                add("VCC_5V", ref, str(gp_pin))
            elif name_u == "BST":
                # Bootstrap — connects to SW via cap (same net for routing)
                add(f"BST_{ref}", ref, str(gp_pin))
            elif name_u == "FB":
                # Feedback — own net (resistor divider sets voltage)
                add(f"FB_{ref}", ref, str(gp_pin))
            else:
                # Generic GPIO — create a named control net
                add(f"CTRL_{gp_name}", ref, str(gp_pin))

        # ── Interface pins ────────────────────────────────────────────────
        ifaces = pins.get("interfaces", {})

        # I2C — shared bus (matches I2C, I2C0, I2C_1, etc.)
        i2c_keys = find_iface_keys(ifaces, "I2C")
        if i2c_keys:
            i2c = ifaces[i2c_keys[0]]
            if "SDA" in i2c:
                add("I2C_SDA", ref, i2c["SDA"])
            if "SCL" in i2c:
                add("I2C_SCL", ref, i2c["SCL"])

        # SPI — shared MOSI/MISO/SCK, individual CS per peripheral
        # Matches SPI, SPI_VSPI, SPI0, SPI_HSPI, SPI1, etc.
        spi_keys = find_iface_keys(ifaces, "SPI")
        if spi_keys:
            spi_key = pick_primary_bus(spi_keys, SPI_BUS_PRIORITY)
            spi = ifaces[spi_key]
            if "MOSI" in spi:
                add("SPI_MOSI", ref, spi["MOSI"])
            if "MISO" in spi:
                add("SPI_MISO", ref, spi["MISO"])
            if "SCK" in spi:
                add("SPI_SCK", ref, spi["SCK"])
            if "CS" in spi:
                # MCU has multiple CS lines; peripherals each get their own
                if comp.get("category") == "mcu":
                    add("SPI_CS_1", ref, spi["CS"])
                else:
                    spi_cs_counter[0] += 1
                    cs_net = f"SPI_CS_{spi_cs_counter[0]}"
                    add(cs_net, ref, spi["CS"])

        # UART (matches UART, UART0, UART2, etc.)
        uart_keys = find_iface_keys(ifaces, "UART")
        if uart_keys:
            # Skip UART0 on ESP32 (USB serial) — use next available
            uart_key = uart_keys[0]
            for uk in sorted(uart_keys):
                iface_data = ifaces[uk]
                if iface_data.get("note", "").lower().find("usb serial") >= 0:
                    continue
                if iface_data.get("note", "").lower().find("avoid") >= 0:
                    continue
                uart_key = uk
                break
            uart = ifaces[uart_key]
            uart_counter[0] += 1
            n = uart_counter[0]
            if "TX" in uart:
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

    # ── Second pass: connector key_pins + auto-added passive wiring ─────
    # Reset instance counters for second pass
    instance_idx2 = {}
    # Track which I2C pull-up index we're on (0=SDA, 1=SCL)
    i2c_pullup_idx = [0]

    for rc in resolved_list:
        cid = rc.get("component_id", "")
        comp = db.get(cid, {})
        if not comp:
            continue

        idx = instance_idx2.get(cid, 0)
        instance_idx2[cid] = idx + 1

        refs_for_cid = comp_ref.get(cid, [])
        if not refs_for_cid:
            continue
        ref = refs_for_cid[min(idx, len(refs_for_cid) - 1)]

        pins = comp.get("pins", {})
        reason = rc.get("reason", "")
        role = comp.get("generic_role", "")

        # ── Connector key_pins (VBUS, GND, CC, D+, D-) ──────────────
        for kp in pins.get("key_pins", []):
            name = kp.get("name", "")
            kp_net = kp.get("net", "")
            kp_pins = kp.get("pins", [])

            # Map connector pin names to nets
            if kp_net:
                net = power_net_name(kp_net)
                for pad in kp_pins:
                    add(net, ref, pad)
            elif name == "CC1":
                for pad in kp_pins:
                    add("USB_CC1", ref, pad)
            elif name == "CC2":
                for pad in kp_pins:
                    add("USB_CC2", ref, pad)
            elif name in ("D+", "DP"):
                for pad in kp_pins:
                    add("USB_DP", ref, pad)
            elif name in ("D-", "DM"):
                for pad in kp_pins:
                    add("USB_DM", ref, pad)

        # ── Auto-added passives: wire based on generic_role ──────────
        if not rc.get("auto_added"):
            continue

        if role == "decoupling_100nf" or role == "bulk_decoupling":
            # Decoupling cap: Pin 1 → power rail, Pin 2 → GND
            # Determine power rail from reason text
            pwr_net = "VCC_3V3"  # default
            if "5V" in reason or "VBUS" in reason:
                pwr_net = "VCC_5V"
            elif "VBAT" in reason:
                pwr_net = "VBAT"
            add(pwr_net, ref, "1")
            add("GND", ref, "2")

        elif role == "i2c_pull_up":
            # I2C pull-up: Pin 1 → VCC_3V3, Pin 2 → SDA or SCL
            signal = "I2C_SDA" if "SDA" in reason else "I2C_SCL"
            add("VCC_3V3", ref, "1")
            add(signal, ref, "2")

        elif role == "usb_cc_pull_down":
            # CC pull-down: Pin 1 → CC1 or CC2, Pin 2 → GND
            # First instance → CC1, second → CC2
            cc_net = "USB_CC1" if i2c_pullup_idx[0] == 0 else "USB_CC2"
            i2c_pullup_idx[0] += 1
            add(cc_net, ref, "1")
            add("GND", ref, "2")

        elif role == "usb_vbus_decoupling":
            # VBUS cap: Pin 1 → VBUS, Pin 2 → GND
            add("VBUS", ref, "1")
            add("GND", ref, "2")

        elif not role:
            # Components without generic_role — use auto_add_rule to infer
            rule = comp.get("auto_add_rule", "")
            category = comp.get("category", "")

            if cid == "ferrite_bead_600r" or "ferrite" in cid:
                # Ferrite bead in VBUS path: both pins on VBUS
                # (FreeRouting routes trace through component)
                add("VBUS", ref, "1")
                add("VBUS", ref, "2")

            elif cid == "cmc_usb" or "cmc" in cid:
                # Common-mode choke: L1 on D+, L2 on D-
                add("USB_DP", ref, "1")
                add("USB_DP", ref, "2")
                add("USB_DM", ref, "3")
                add("USB_DM", ref, "4")

            elif cid == "usblc6_2sc6":
                # ESD protection on USB data lines
                # Real USBLC6-2SC6 SOT-23-6: pin 1=IO1, 2=GND, 3=IO2,
                # 4=IO2, 5=VBUS, 6=IO1
                add("USB_DP",  ref, "1")
                add("GND",     ref, "2")
                add("USB_DM",  ref, "3")
                add("USB_DM",  ref, "4")
                add("VBUS",    ref, "5")
                add("USB_DP",  ref, "6")

            elif cid == "fs8205a":
                # Dual N-FET for battery protection (DW01A companion)
                # KiCad Q_Dual_NMOS_S1G1S2G2D2D2D1D1 pin mapping:
                # Pin 1: S1, Pin 2: G1, Pin 3: S2, Pin 4: G2,
                # Pin 5-6: D2, Pin 7-8: D1
                add("GND_BATT", ref, "1")   # S1 → battery negative
                add("CTRL_OD",  ref, "2")   # G1 → DW01A overdischarge
                add("GND",      ref, "3")   # S2 → system ground
                add("CTRL_OC",  ref, "4")   # G2 → DW01A overcurrent

        # ── LiPo charger support roles ────────────────────────────────
        if role == "charge_current_set":
            # RPROG resistor: pin 1 → TP4056 PROG, pin 2 → GND
            add("CTRL_PROG", ref, "1")
            add("GND", ref, "2")

        elif role == "charging_indicator":
            # Charge LED: KiCad pin 2=Anode→VCC, pin 1=Cathode→~CHRG
            add("VCC_5V",    ref, "2")
            add("CTRL_CHRG", ref, "1")

        elif role == "charge_complete_indicator":
            # Standby LED: KiCad pin 2=Anode→VCC, pin 1=Cathode→~STDBY
            add("VCC_5V",     ref, "2")
            add("CTRL_STDBY", ref, "1")

        elif role == "ntc_substitute":
            # NTC disable resistor: pin 1 → TP4056 TEMP, pin 2 → GND
            add("CTRL_TEMP", ref, "1")
            add("GND", ref, "2")

    # ── Third pass: allocate MCU GPIOs to unconnected control nets ────────
    mcu_ref = None
    mcu_comp = None
    mcu_cid = None
    for pc in comp_list:
        cid_check = pc.get("component_id", "")
        comp_check = db.get(cid_check, {})
        if comp_check.get("category") == "mcu":
            mcu_ref = pc.get("ref")
            mcu_comp = comp_check
            mcu_cid = cid_check
            break

    if mcu_ref and mcu_comp:
        mcu_pins = mcu_comp.get("pins", {})
        gpio_available = list(mcu_pins.get("gpio_available", []))
        gpio_input_only = set(mcu_pins.get("gpio_input_only", []))

        # Usable GPIOs: exclude input-only pins
        gpio_pool = [g for g in gpio_available if g not in gpio_input_only]

        # Pads already used by the MCU in existing nets
        used_pads = set()
        for endpoints in nets.values():
            for ep in endpoints:
                if ep["ref"] == mcu_ref:
                    used_pads.add(ep["pad"])

        free_gpios = [g for g in gpio_pool if normalise_pad(g) not in used_pads]

        # Allocate GPIOs to control nets that lack an MCU endpoint
        gpio_idx = 0
        for net_name in sorted(nets.keys()):
            if not net_name.startswith("CTRL_"):
                continue
            # Skip if MCU already on this net
            if any(ep["ref"] == mcu_ref for ep in nets[net_name]):
                continue
            if gpio_idx < len(free_gpios):
                add(net_name, mcu_ref, normalise_pad(free_gpios[gpio_idx]))
                gpio_idx += 1
            else:
                engineer_review.append({
                    "ref": mcu_ref,
                    "component_id": mcu_cid,
                    "display_name": mcu_comp.get("display_name", mcu_cid),
                    "reasons": [f"No free GPIO available for control net {net_name}"],
                })

    return nets, engineer_review


# ─── Net class classification ────────────────────────────────────────────────

# Net class definitions: {class_name: {clearance, track_width, via_dia, via_drill}}
NET_CLASS_DEFS = {
    "Power":     {"clearance": 0.2,  "track_width": 0.3,  "via_dia": 0.6, "via_drill": 0.3},
    "HighSpeed": {"clearance": 0.15, "track_width": 0.2,  "via_dia": 0.6, "via_drill": 0.3},
    "Analog":    {"clearance": 0.2,  "track_width": 0.2,  "via_dia": 0.6, "via_drill": 0.3},
    "Default":   {"clearance": 0.15, "track_width": 0.2,  "via_dia": 0.6, "via_drill": 0.3},
}

# Prefixes for high-speed classification
_HIGHSPEED_PREFIXES = ("SPI_", "USB_", "I2S_", "CAN_")


def classify_nets(nets):
    """Classify each net into a net class based on name patterns.

    Returns dict ready for JSON serialisation:
      {
        "Power":     {clearance, track_width, via_dia, via_drill},
        "HighSpeed": {...},
        "Analog":    {...},
        "Default":   {...},
        "assignments": {net_name: class_name, ...}
      }
    """
    assignments = {}
    for name in nets:
        if is_power_net(name):
            assignments[name] = "Power"
        elif any(name.startswith(p) for p in _HIGHSPEED_PREFIXES):
            assignments[name] = "HighSpeed"
        elif name.startswith(("ADC_", "AREF", "SENSOR_ANALOG", "ONEWIRE_")):
            assignments[name] = "Analog"
        else:
            assignments[name] = "Default"
    result = dict(NET_CLASS_DEFS)
    result["assignments"] = assignments
    return result


def is_power_net(name):
    """Check whether a net name represents a power rail."""
    return name in ("GND", "VCC_3V3", "VCC_5V", "VBAT", "VBAT_COIN",
                    "VBUS", "GND_BATT")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python netlist.py <job_dir>")
        sys.exit(1)

    from refdes import assign_refs

    job_dir  = Path(sys.argv[1])
    db       = load_db()
    resolved = load_json(job_dir / "resolved.json")

    if not resolved:
        print(f"ERROR: resolved.json not found in {job_dir}")
        sys.exit(1)

    comp_list = assign_refs(resolved["resolved_components"], db)
    nets, engineer_review = build_netlist(resolved, comp_list, db)

    result = {
        "nets":            nets,
        "net_count":       len(nets),
        "engineer_review": engineer_review,
    }

    out_path = job_dir / "netlist.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    # Classify nets and write net_classes.json
    nc = classify_nets(nets)
    nc_path = job_dir / "net_classes.json"
    with open(nc_path, "w", encoding="utf-8") as f:
        json.dump(nc, f, indent=2)

    # Summary counts per class
    class_counts = {}
    for cls in nc.get("assignments", {}).values():
        class_counts[cls] = class_counts.get(cls, 0) + 1

    print(f"[netlist] Generated {len(nets)} nets for "
          f"{len(comp_list)} components")
    print(f"[netlist] Net classes: "
          + ", ".join(f"{k}={v}" for k, v in sorted(class_counts.items())))
    if engineer_review:
        print(f"[netlist] {len(engineer_review)} component(s) flagged for engineer review:")
        for flag in engineer_review:
            print(f"  {flag['ref']} ({flag['display_name']}): {'; '.join(flag['reasons'])}")
    print(f"[netlist] Saved to {out_path}")


if __name__ == "__main__":
    main()
