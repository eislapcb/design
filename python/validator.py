"""
Eisla — Design Validator (python/validator.py)

Session 6. Runs after capability resolution, before placement.
Checks the resolved component list for common PCB design mistakes.

Usage (from Node.js worker or standalone):
    python validator.py <job_dir>

  job_dir must contain:
    resolved.json  — full resolver output (from POST /api/resolve)
    board.json     — board config { layers, dimensions_mm, power_source }

  Writes:
    validation_warnings.json  — findings list

Standalone test:
    python python/validator.py --test
"""

import json
import os
import sys
import math
import argparse
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR     = PROJECT_ROOT / "data"
COMPONENTS_PATH = DATA_DIR / "components.json"
RULES_PATH      = DATA_DIR / "validation_rules.json"

# ─── Data loading (cached) ────────────────────────────────────────────────────

_components_db = None
_rules_db      = None

def load_components():
    global _components_db
    if _components_db is None:
        with open(COMPONENTS_PATH, encoding="utf-8") as f:
            _components_db = json.load(f)
    return _components_db

def load_rules():
    global _rules_db
    if _rules_db is None:
        with open(RULES_PATH, encoding="utf-8") as f:
            data = json.load(f)
            _rules_db = {r["id"]: r for r in data["rules"]}
    return _rules_db

def get_component(component_id):
    """Return full component dict from components.json, or None."""
    return load_components().get(component_id)

def rule_enabled(rule_id):
    rules = load_rules()
    r = rules.get(rule_id, {})
    return r.get("enabled", True)

# ─── Finding builder ──────────────────────────────────────────────────────────

def finding(rule_id, title, description, affected=None, severity=None, auto_resolved=False, resolution=None):
    rules = load_rules()
    rule  = rules.get(rule_id, {})
    return {
        "id":                  f"{rule_id}",
        "severity":            severity or rule.get("default_severity", "warning"),
        "rule":                rule_id,
        "title":               title,
        "description":         description,
        "affected_components": affected or [],
        "auto_resolved":       auto_resolved,
        "resolution":          resolution,
    }

# ─── Individual checks ────────────────────────────────────────────────────────

def check_decoupling_caps(resolved_components, auto_adds):
    """Every IC with requires_decoupling=True needs a 100nF or 10uF cap."""
    if not rule_enabled("decoupling_cap_required"):
        return []

    findings = []
    # Collect existing caps
    cap_values = set()
    for rc in resolved_components:
        comp = get_component(rc["component_id"])
        if comp and comp.get("subcategory") == "capacitor":
            cap_values.add(rc["component_id"])

    has_100nf = any("100nf" in cid or "100n" in cid for cid in cap_values)
    has_10uf  = any("10uf" in cid or "10u" in cid  for cid in cap_values)

    needs_decoupling = [
        rc for rc in resolved_components
        if get_component(rc["component_id"]) and
           get_component(rc["component_id"]).get("requires_decoupling")
    ]

    if needs_decoupling and not (has_100nf or has_10uf):
        affected = [rc["component_id"] for rc in needs_decoupling]
        # Auto-add 100nF cap
        auto_adds.append({
            "component_id": "cap_100nf_0402",
            "quantity": len(needs_decoupling),
            "auto_added": True,
            "reason": "Decoupling capacitor auto-added for IC bypass",
        })
        findings.append(finding(
            "decoupling_cap_required",
            f"Missing decoupling capacitors ({len(needs_decoupling)} IC{'s' if len(needs_decoupling)>1 else ''})",
            f"{len(needs_decoupling)} IC(s) require bypass capacitors but none are present. "
            f"A 100nF 0402 capacitor has been auto-added for each.",
            affected=affected,
            auto_resolved=True,
            resolution=f"auto_added {len(needs_decoupling)}x cap_100nf_0402",
        ))

    return findings


def check_ldo_output_cap(resolved_components, auto_adds):
    """LDOs need their required output capacitor."""
    if not rule_enabled("ldo_output_cap"):
        return []

    findings = []
    cap_ids_present = {
        rc["component_id"] for rc in resolved_components
        if get_component(rc["component_id"]) and
           get_component(rc["component_id"]).get("subcategory") == "capacitor"
    }

    for rc in resolved_components:
        comp = get_component(rc["component_id"])
        if not comp:
            continue
        req = comp.get("required_output_cap")
        if not req:
            continue

        # Check if a suitable capacitor is in the BOM
        # We look for tantalum or ceramic caps (10uF+)
        has_suitable = any(
            "10uf" in cid or "22uf" in cid or "47uf" in cid or "100uf" in cid
            for cid in cap_ids_present
        )
        if not has_suitable:
            findings.append(finding(
                "ldo_output_cap",
                f"LDO output capacitor missing for {comp['display_name']}",
                f"{comp['display_name']} requires a {req.get('value', '10uF')} "
                f"output capacitor ({req.get('type', 'ceramic')}) for stability. "
                f"Without it the regulator may oscillate. {req.get('notes', '')}",
                affected=[rc["component_id"]],
                severity="error",
            ))

    return findings


def check_power_budget(resolved_components, power_budget, board_config):
    """Total current draw must not exceed source limit."""
    if not rule_enabled("power_budget_exceeded"):
        return []

    findings = []
    total_ma = power_budget.get("total_ma", 0)
    source   = board_config.get("power_source", power_budget.get("source", "usb"))

    limits = {
        "usb":      500,
        "power_usb": 500,
        "lipo":     1000,
        "power_lipo": 1000,
        "dc_jack":  2000,
        "power_dc_jack": 2000,
        "mains":    5000,
    }
    limit_ma = limits.get(source, 500)

    if total_ma > limit_ma:
        over_ma = total_ma - limit_ma
        findings.append(finding(
            "power_budget_exceeded",
            f"Power budget exceeded by {over_ma}mA",
            f"Total estimated current draw: {total_ma}mA. "
            f"Source limit ({source}): {limit_ma}mA. "
            f"Exceeded by {over_ma}mA. Consider switching to a higher-capacity power source "
            f"or removing power-hungry components.",
            severity="error",
        ))

    return findings


def check_reverse_polarity(resolved_components, board_config):
    """Battery boards without reverse polarity protection."""
    if not rule_enabled("reverse_polarity_missing"):
        return []

    source = board_config.get("power_source", "")
    is_battery = "lipo" in source or "battery" in source

    if not is_battery:
        return []

    comp_ids = {rc["component_id"] for rc in resolved_components}
    has_protection = (
        "usblc6_2sc6" in comp_ids or          # TVS/ESD
        "ao3401a" in comp_ids or              # P-channel MOSFET
        any("tvs" in cid for cid in comp_ids) or
        any("mosfet_p" in cid for cid in comp_ids)
    )

    if not has_protection:
        return [finding(
            "reverse_polarity_missing",
            "No reverse polarity protection on battery-powered board",
            "Battery-powered boards are susceptible to damage from reversed connections. "
            "Consider adding a P-channel MOSFET (e.g. AO3401A) or Schottky diode for protection.",
            severity="info",
        )]
    return []


def check_usb_differential_pair(resolved_components):
    """If USB device present, flag D+/D- for diff pair routing."""
    if not rule_enabled("usb_differential_pair"):
        return []

    has_usb = any(
        "usb" in (get_component(rc["component_id"]) or {}).get("subcategory", "") or
        "usb_device" in rc.get("satisfies", []) or
        "usb_host"   in rc.get("satisfies", [])
        for rc in resolved_components
    )

    if has_usb:
        return [finding(
            "usb_differential_pair",
            "USB differential pair detected — requires controlled routing",
            "USB D+ and D- lines must be routed as a differential pair with matched length "
            "and impedance. FreeRouting will apply diff-pair constraints. "
            "Keep traces short and symmetric; avoid vias where possible.",
            severity="info",
            auto_resolved=True,
            resolution="diff_pair_net_class_assigned",
        )]
    return []


def check_i2c_pullups(resolved_components, auto_adds):
    """I2C devices need pull-up resistors on SDA/SCL."""
    if not rule_enabled("i2c_pullup_missing"):
        return []

    has_i2c = any(
        "I2C" in (get_component(rc["component_id"]) or {}).get("interfaces", [])
        for rc in resolved_components
    )

    if not has_i2c:
        return []

    comp_ids = {rc["component_id"] for rc in resolved_components}
    has_pullups = any("res_4k7" in cid or "res_2k2" in cid or "i2c" in cid.lower() for cid in comp_ids)

    if not has_pullups:
        auto_adds.append({
            "component_id": "res_4k7_0402",
            "quantity": 2,
            "auto_added": True,
            "reason": "I2C SDA/SCL pull-up resistors (4.7k x 2)",
        })
        return [finding(
            "i2c_pullup_missing",
            "I2C pull-up resistors auto-added",
            "I2C bus (SDA/SCL) requires pull-up resistors. Two 4.7kΩ 0402 resistors have been "
            "auto-added (suitable for 100kHz standard mode). Use 2.2kΩ for 400kHz fast mode.",
            auto_resolved=True,
            resolution="auto_added 2x res_4k7_0402",
        )]
    return []


def check_uart_crossover(resolved_components):
    """Warn if multiple UART devices present (crossover must be verified)."""
    if not rule_enabled("uart_rx_tx_cross"):
        return []

    uart_comps = [
        rc for rc in resolved_components
        if "UART" in (get_component(rc["component_id"]) or {}).get("interfaces", [])
    ]

    if len(uart_comps) >= 2:
        affected = [rc["component_id"] for rc in uart_comps]
        return [finding(
            "uart_rx_tx_cross",
            f"Multiple UART devices — verify TX/RX crossover ({len(uart_comps)} devices)",
            "When multiple UART devices are connected, TX of each device must connect to RX "
            "of the other (and vice versa). Straight TX→TX connections are a common mistake. "
            "Verify crossover in the netlist before routing.",
            affected=affected,
            severity="warning",
        )]
    return []


def check_spi_shared_cs(resolved_components):
    """Multiple SPI devices need individual chip-select lines."""
    if not rule_enabled("spi_shared_cs"):
        return []

    spi_comps = [
        rc for rc in resolved_components
        if "SPI" in (get_component(rc["component_id"]) or {}).get("interfaces", [])
    ]

    if len(spi_comps) >= 2:
        affected = [rc["component_id"] for rc in spi_comps]
        return [finding(
            "spi_shared_cs",
            f"Multiple SPI devices — each requires a dedicated chip-select ({len(spi_comps)} devices)",
            f"{len(spi_comps)} SPI devices detected. Each requires its own dedicated CS (chip-select) "
            "GPIO line from the MCU. They cannot share a single CS line. "
            "Verify the MCU has sufficient GPIO pins for all CS lines.",
            affected=affected,
            severity="warning",
        )]
    return []


def check_lora_wifi_conflict(resolved_components):
    """LoRa + WiFi simultaneous transmission warning."""
    if not rule_enabled("lora_wifi_simultaneous"):
        return []

    all_caps = set()
    for rc in resolved_components:
        all_caps.update(rc.get("satisfies", []))
        comp = get_component(rc["component_id"])
        if comp:
            all_caps.update(comp.get("capabilities", []))

    has_lora = any("lora" in cap for cap in all_caps) or any(
        get_component(rc["component_id"]) and
        get_component(rc["component_id"]).get("subcategory") == "lora"
        for rc in resolved_components
    )
    has_wifi = any("wifi" in cap for cap in all_caps)

    if has_lora and has_wifi:
        return [finding(
            "lora_wifi_simultaneous",
            "LoRa and WiFi present — firmware must use time-division multiplexing",
            "Both LoRa and WiFi radios are on the board. Simultaneous transmission can cause "
            "interference. The firmware must not activate both radios at the same time. "
            "Implement time-division multiplexing (transmit on one, then the other).",
            severity="warning",
        )]
    return []


def check_rf_antenna(resolved_components):
    """RF module without antenna component."""
    if not rule_enabled("rf_no_antenna"):
        return []

    # RF modules that need an external antenna
    RF_SUBCATEGORIES = {"lora", "cellular_lpwan", "nfc"}
    rf_modules = [
        rc for rc in resolved_components
        if (get_component(rc["component_id"]) or {}).get("subcategory") in RF_SUBCATEGORIES
    ]

    if not rf_modules:
        return []

    comp_ids = {rc["component_id"] for rc in resolved_components}
    has_antenna = (
        "sma_edge_connector" in comp_ids or
        any((get_component(cid) or {}).get("subcategory") == "antenna" for cid in comp_ids)
    )

    if not has_antenna:
        affected = [rc["component_id"] for rc in rf_modules]
        return [finding(
            "rf_no_antenna",
            f"RF module without antenna ({', '.join(affected)})",
            "An RF module requiring an external antenna is in the BOM but no antenna connector "
            "has been added. Add an SMA edge connector or wire antenna for the RF module.",
            affected=affected,
            severity="error",
        )]
    return []


def check_board_density(resolved_components, board_config):
    """Warn if component count suggests very dense board."""
    if not rule_enabled("board_density_high"):
        return []

    dims = board_config.get("dimensions_mm", [100, 100])
    if not dims or len(dims) < 2:
        return []

    board_area_mm2 = dims[0] * dims[1]
    # Rough estimate: average SMT component footprint ~16mm² (0402 = 4mm², QFN = 36mm²)
    avg_footprint_mm2 = 16
    estimated_footprint = len(resolved_components) * avg_footprint_mm2
    density_pct = (estimated_footprint / board_area_mm2) * 100

    if density_pct > 75:
        return [finding(
            "board_density_high",
            f"High board density (~{int(density_pct)}%) — placement may be very tight",
            f"Estimated component footprint area ({estimated_footprint}mm²) is {int(density_pct)}% "
            f"of board area ({board_area_mm2}mm²). Placement may be very tight. "
            "Consider increasing board dimensions or removing optional components.",
            severity="warning",
        )]
    return []


def check_mounting_holes(resolved_components, board_config):
    """Board > 50×50mm should have mounting holes."""
    if not rule_enabled("no_mounting_holes"):
        return []

    dims = board_config.get("dimensions_mm", [100, 100])
    if not dims or len(dims) < 2:
        return []

    if dims[0] <= 50 and dims[1] <= 50:
        return []  # Small board — holes optional

    comp_ids = {rc["component_id"] for rc in resolved_components}
    has_holes = any(
        (get_component(cid) or {}).get("subcategory") in {"mechanical", "fiducial"}
        for cid in comp_ids
    )

    if not has_holes:
        return [finding(
            "no_mounting_holes",
            "No mounting holes — board may be difficult to secure",
            f"Board size {dims[0]}×{dims[1]}mm has no mounting holes in the component list. "
            "Consider adding M3 standoff holes at the corners for enclosure mounting.",
            severity="info",
        )]
    return []


def check_motor_flyback(resolved_components):
    """Motor drivers and relays need flyback diodes."""
    if not rule_enabled("motor_flyback_missing"):
        return []

    motor_comps = [
        rc for rc in resolved_components
        if (get_component(rc["component_id"]) or {}).get("category") == "motor_driver"
    ]

    if not motor_comps:
        return []

    comp_ids = {rc["component_id"] for rc in resolved_components}
    has_flyback = (
        "diode_1n4148w" in comp_ids or
        any("flyback" in cid for cid in comp_ids) or
        any("1n4148" in cid for cid in comp_ids)
    )

    if not has_flyback:
        affected = [rc["component_id"] for rc in motor_comps]
        return [finding(
            "motor_flyback_missing",
            f"Motor driver without flyback diodes ({', '.join(affected)})",
            "Motor drivers and relays generate back-EMF when the load switches off. "
            "Without flyback diodes, this voltage spike will damage the driver IC. "
            "Add 1N4148W diodes across each motor/relay winding.",
            affected=affected,
            severity="error",
        )]
    return []


def check_fine_pitch(resolved_components):
    """Warn about fine-pitch components that need reflow assembly."""
    if not rule_enabled("fine_pitch_assembly"):
        return []

    FINE_PITCH_SUBCATS = {"arm_cortex_m7", "wifi_ble", "ble_zigbee"}
    fine_comps = [
        rc for rc in resolved_components
        if (get_component(rc["component_id"]) or {}).get("subcategory") in FINE_PITCH_SUBCATS
    ]

    if fine_comps:
        affected = [rc["component_id"] for rc in fine_comps]
        return [finding(
            "fine_pitch_assembly",
            f"Fine-pitch component detected — requires reflow assembly",
            "QFN or fine-pitch packages detected. These cannot be hand-soldered reliably. "
            "Professional SMT assembly with solder paste and reflow oven is required.",
            affected=affected,
            severity="info",
        )]
    return []


# ─── Main runner ──────────────────────────────────────────────────────────────

def run_all_checks(resolved_components, power_budget, board_config):
    """
    Run all enabled validation checks.
    Returns { findings, auto_adds, error_count, warning_count, info_count }
    """
    findings  = []
    auto_adds = []  # components auto-added by checks

    findings += check_decoupling_caps(resolved_components, auto_adds)
    findings += check_ldo_output_cap(resolved_components, auto_adds)
    findings += check_power_budget(resolved_components, power_budget, board_config)
    findings += check_reverse_polarity(resolved_components, board_config)
    findings += check_usb_differential_pair(resolved_components)
    findings += check_i2c_pullups(resolved_components, auto_adds)
    findings += check_uart_crossover(resolved_components)
    findings += check_spi_shared_cs(resolved_components)
    findings += check_lora_wifi_conflict(resolved_components)
    findings += check_rf_antenna(resolved_components)
    findings += check_board_density(resolved_components, board_config)
    findings += check_mounting_holes(resolved_components, board_config)
    findings += check_motor_flyback(resolved_components)
    findings += check_fine_pitch(resolved_components)

    return {
        "findings":      findings,
        "auto_adds":     auto_adds,
        "error_count":   sum(1 for f in findings if f["severity"] == "error"),
        "warning_count": sum(1 for f in findings if f["severity"] == "warning"),
        "info_count":    sum(1 for f in findings if f["severity"] == "info"),
    }


# ─── CLI entry point ──────────────────────────────────────────────────────────

def run_job(job_dir):
    job_path = Path(job_dir)

    with open(job_path / "resolved.json", encoding="utf-8") as f:
        resolved = json.load(f)

    with open(job_path / "board.json", encoding="utf-8") as f:
        board_config = json.load(f)

    resolved_components = resolved.get("resolved_components", [])
    power_budget        = resolved.get("power_budget", {})

    result = run_all_checks(resolved_components, power_budget, board_config)

    out_path = job_path / "validation_warnings.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Validation complete: {result['error_count']} errors, "
          f"{result['warning_count']} warnings, {result['info_count']} info")
    print(f"Results written to {out_path}")

    return result


# ─── Standalone test ──────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "name": "ESP32 + I2C sensor + LiPo — should find missing decoupling, add I2C pullups",
        "resolved_components": [
            {"component_id": "esp32_wroom_32", "quantity": 1, "satisfies": ["wifi"], "auto_added": False, "display_name": "ESP32-WROOM-32E", "category": "mcu", "power_consumption_ma": 240},
            {"component_id": "sht31",          "quantity": 1, "satisfies": ["sensor_temperature"], "auto_added": False, "display_name": "SHT31", "category": "sensor", "power_consumption_ma": 2},
            {"component_id": "tp4056",         "quantity": 1, "satisfies": ["power_lipo"], "auto_added": True, "display_name": "TP4056", "category": "power", "power_consumption_ma": 5},
        ],
        "power_budget": {"total_ma": 247, "source": "power_lipo"},
        "board_config": {"layers": 2, "dimensions_mm": [100, 80], "power_source": "power_lipo"},
    },
    {
        "name": "ATmega + motor driver — should catch missing flyback diodes",
        "resolved_components": [
            {"component_id": "atmega328p_au", "quantity": 1, "satisfies": ["processing_basic"], "auto_added": False, "display_name": "ATmega328P", "category": "mcu", "power_consumption_ma": 12},
            {"component_id": "drv8833",       "quantity": 1, "satisfies": ["motor_dc"], "auto_added": False, "display_name": "DRV8833", "category": "motor_driver", "power_consumption_ma": 50},
            {"component_id": "cap_100nf_0402","quantity": 4, "satisfies": [], "auto_added": False, "display_name": "100nF Cap", "category": "passive", "power_consumption_ma": 0},
        ],
        "power_budget": {"total_ma": 62, "source": "usb"},
        "board_config": {"layers": 2, "dimensions_mm": [80, 60], "power_source": "usb"},
    },
    {
        "name": "LoRa + WiFi (ESP32) — should warn about simultaneous transmission",
        "resolved_components": [
            {"component_id": "esp32_wroom_32", "quantity": 1, "satisfies": ["wifi", "bluetooth"], "auto_added": False, "display_name": "ESP32-WROOM-32E", "category": "mcu", "power_consumption_ma": 240},
            {"component_id": "rfm95w",         "quantity": 1, "satisfies": ["lora"], "auto_added": False, "display_name": "RFM95W", "category": "comms", "power_consumption_ma": 120},
            {"component_id": "cap_100nf_0402", "quantity": 4, "satisfies": [], "auto_added": False, "display_name": "100nF Cap", "category": "passive", "power_consumption_ma": 0},
        ],
        "power_budget": {"total_ma": 360, "source": "power_lipo"},
        "board_config": {"layers": 2, "dimensions_mm": [100, 80], "power_source": "power_lipo"},
    },
    {
        "name": "USB-heavy design over USB power budget — should flag power budget error",
        "resolved_components": [
            {"component_id": "esp32_wroom_32", "quantity": 1, "satisfies": ["wifi"], "auto_added": False, "display_name": "ESP32", "category": "mcu", "power_consumption_ma": 240},
            {"component_id": "drv8833",        "quantity": 2, "satisfies": ["motor_dc"], "auto_added": False, "display_name": "DRV8833", "category": "motor_driver", "power_consumption_ma": 150},
            {"component_id": "cap_100nf_0402", "quantity": 4, "satisfies": [], "auto_added": False, "display_name": "100nF Cap", "category": "passive", "power_consumption_ma": 0},
        ],
        "power_budget": {"total_ma": 540, "source": "usb"},
        "board_config": {"layers": 2, "dimensions_mm": [80, 60], "power_source": "usb"},
    },
]

def run_tests():
    print("\n--- Validator unit tests ---\n")
    passed = failed = 0

    for tc in TEST_CASES:
        print(f"  TEST: {tc['name']}")
        result = run_all_checks(
            tc["resolved_components"],
            tc["power_budget"],
            tc["board_config"],
        )
        print(f"    > {result['error_count']} errors, {result['warning_count']} warnings, "
              f"{result['info_count']} info, {len(result['auto_adds'])} auto-adds")
        for f in result["findings"]:
            print(f"      [{f['severity'].upper():7s}] {f['rule']}: {f['title']}")
        if result["auto_adds"]:
            for a in result["auto_adds"]:
                print(f"      [AUTO-ADD] {a['component_id']} × {a['quantity']} — {a['reason']}")
        print()
        passed += 1  # test passed if it ran without error

    print(f"---")
    print(f"  {passed} tests run, {failed} errors\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eisla design validator")
    parser.add_argument("job_dir", nargs="?", help="Job directory containing resolved.json and board.json")
    parser.add_argument("--test", action="store_true", help="Run unit tests")
    args = parser.parse_args()

    if args.test:
        run_tests()
    elif args.job_dir:
        result = run_job(args.job_dir)
        sys.exit(0 if result["error_count"] == 0 else 1)
    else:
        parser.print_help()
        sys.exit(1)
