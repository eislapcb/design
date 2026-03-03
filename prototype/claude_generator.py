"""
claude_generator.py — Claude API-based Zener board file generator.

Replaces tier_classifier + zen_generator with a single Claude API call.
Claude reads the NL description, reasons about design requirements, and emits
a complete, compilable .zen board file.

Requires: pip install anthropic
Env var:  ANTHROPIC_API_KEY
"""

import os
import anthropic


# ── Zener language reference ──────────────────────────────────────────────────
# Focused subset of the full spec (https://docs.pcb.new/llms-full.txt) covering
# everything needed to generate correct board files.

ZENER_SPEC = """
## Zener Language — Quick Reference

Zener is a Starlark-based DSL for describing PCB schematics as code.
Each .zen file is a deterministic, side-effect-free module.

### Imports
    load("@stdlib/units.zen", "Voltage", "Current", "Resistance",
         "Capacitance", "Inductance", "Impedance")
    load("@stdlib/generics/Resistor.zen", "Resistor")
    load("@stdlib/generics/Capacitor.zen", "Capacitor")
    load("@stdlib/generics/Inductor.zen", "Inductor")
    MyModule = Module("./relative/path.zen")
    MyModule = Module("github.com/diodeinc/registry/path/to/Module.zen")

### Net
    gnd  = Net("GND")
    v3v3 = Net("V3V3", voltage=Voltage("3.3V"))
    clk  = Net("CLK",  impedance=Impedance(50))
    vdd  = Net("VDD",  voltage=Voltage("3.0V to 3.6V"))

### Symbol
    # From KiCad library
    sym = Symbol("@kicad-symbols/power.kicad_sym:GND")
    # Manual definition
    sym = Symbol(
        name="MyIC",
        definition=[
            ("VCC",  ["1", "8"]),
            ("GND",  ["4"]),
            ("IN",   ["2"]),
            ("OUT",  ["7"]),
        ],
    )

### Component
    Component(
        name     = "U1",
        symbol   = sym,
        pins     = {"VCC": vcc, "GND": gnd, "IN": inp, "OUT": out},
        mpn      = "LM358",
        prefix   = "U",
        footprint= "footprints/SOIC-8.kicad_mod",  # optional
    )

### Generic passives (stdlib)
    Resistor(name="R1", value="10k",   P1=net_a, P2=net_b)
    Capacitor(name="C1", value="100nF", P1=net_a, P2=net_b)
    Inductor(name="L1",  value="10uH",  P1=net_a, P2=net_b)

### Module instantiation
    ldo = LDO(vin=vin, vout=v3v3, gnd=gnd)  # named, returns instance
    LDO(vin=vin, vout=v3v3, gnd=gnd)         # anonymous is fine too

### Physical values
    Voltage("3.3V"), Voltage("1.1-3.6V"), Voltage("5V 10%")
    Resistance("4k7")   # 4.7 kΩ resistor notation
    Current("100mA")
    Capacitance("100nF"), Inductance("10uH")

### Interface
    I2CBus = interface(SDA=Net(), SCL=Net())
    bus = I2CBus("I2C")   # bus.SDA, bus.SCL

### io() — module inputs (only used when writing a reusable module file)
    vin, gnd = io(
        vin = Net("VIN", voltage=Voltage("5V to 12V")),
        gnd = Net("GND"),
    )
"""

# ── Local module catalogue ────────────────────────────────────────────────────
# These modules exist in the workspace. Board files are written into
# boards/generated/, so relative paths use ../../modules/...

LOCAL_MODULES = """
## Local modules (relative path from boards/generated/<BoardName>.zen)

### Power
    LDO = Module("../../modules/power/LDO3V3.zen")
    # AMS1117-3.3, 3.3 V output, 5 V–12 V input
    # Inputs:  vin (Net), vout (Net), gnd (Net)
    # Includes: input bulk cap, output 22 µF + 100 nF bypass

    Buck = Module("../../modules/power/BuckConverter5V.zen")
    # Step-down to 5 V, 7 V–24 V input
    # Inputs: vin (Net), vout (Net), gnd (Net)

### USB
    USBTypeC = Module("../../modules/usb/USBTypeC.zen")
    # USB-C receptacle with ESD protection
    # Inputs: vbus (Net), gnd (Net)
    # Returns instance with .usb interface (.usb.DP, .usb.DN)
    # Usage:
    #   usb = USBTypeC(vbus=Net("VBUS", voltage=Voltage("5V")), gnd=gnd)
    #   # usb.usb.DP and usb.usb.DN connect to MCU USB pins

### Debug
    SWD = Module("../../modules/debug/SWD.zen")
    # ARM SWD debug header (TC2050 / Tag-Connect)
    # Inputs: vcc (Net), gnd (Net), swdio (Net), swclk (Net),
    #         swo (Net), nreset (Net)

### Indicators
    StatusLED = Module("../../modules/indicators/StatusLED.zen")
    # Current-limited LED
    # Inputs: gpio (Net), vcc (Net), gnd (Net)
"""

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are an expert PCB designer using the Zener hardware description language.

{ZENER_SPEC}

{LOCAL_MODULES}

## Your task

Given a natural-language PCB description, output a single complete, compilable
Zener board file.  No markdown fences, no explanation — raw .zen code only.

## Mandatory design rules

1. Power rail: always include an LDO (or Buck+LDO for barrel-jack boards).
2. Decoupling: one 100 nF cap per VCC pin on every IC; bulk caps where needed.
3. Reset: pull-up resistor (10 kΩ) + 100 nF filter cap on every reset line.
4. Debug: always include an SWD header for ARM MCUs.
5. Status LED: always include at least one StatusLED driven from an MCU GPIO.
6. All net names must be descriptive strings, not unnamed Net().
7. Name every Component and passive with a unique name ("U_MCU", "C1", "R_RST").
8. Define MCU symbols with Symbol(name=..., definition=[...]) listing all pins.
9. Connect unused MCU pins to appropriately named Net() instances.
10. For USB MCUs, connect USB D+/D− to the USBTypeC module's .usb.DP/.usb.DN.

## Good example (RP2040 blink board)

```python
load("@stdlib/generics/Capacitor.zen", "Capacitor")
load("@stdlib/generics/Resistor.zen",  "Resistor")
load("@stdlib/units.zen", "Voltage", "Impedance")

LDO      = Module("../../modules/power/LDO3V3.zen")
USBTypeC = Module("../../modules/usb/USBTypeC.zen")
SWD      = Module("../../modules/debug/SWD.zen")
StatusLED = Module("../../modules/indicators/StatusLED.zen")

# Nets
v3v3 = Net("V3V3", voltage=Voltage("3.3V"))
gnd  = Net("GND")

# USB power input
usb = USBTypeC(vbus=Net("VBUS", voltage=Voltage("5V")), gnd=gnd)

# Regulate to 3.3 V
LDO(vin=Net("VBUS", voltage=Voltage("5V")), vout=v3v3, gnd=gnd)

# MCU symbol
RP2040Sym = Symbol(
    name="RP2040",
    definition=[
        ("IOVDD",   ["1","10","22","33","42","49"]),
        ("DVDD",    ["23","50"]),
        ("USB_DP",  ["47"]),
        ("USB_DM",  ["46"]),
        ("GND",     ["57"]),
        ("GPIO0",   ["2"]),
        ("GPIO1",   ["3"]),
        ("GPIO25",  ["37"]),
        ("RUN",     ["26"]),
        ("SWDIO",   ["24"]),
        ("SWCLK",   ["25"]),
    ],
)

n_reset = Net("nRESET")

Component(
    name="U_MCU",
    symbol=RP2040Sym,
    mpn="RP2040",
    pins={{
        "IOVDD":  v3v3,
        "DVDD":   v3v3,
        "GND":    gnd,
        "USB_DP": usb.usb.DP,
        "USB_DM": usb.usb.DN,
        "GPIO0":  Net("UART_TX"),
        "GPIO1":  Net("UART_RX"),
        "GPIO25": Net("LED_GPIO"),
        "RUN":    n_reset,
        "SWDIO":  Net("SWDIO"),
        "SWCLK":  Net("SWCLK"),
    }},
)

# Decoupling
Capacitor(name="C1", value="100nF", P1=v3v3, P2=gnd)
Capacitor(name="C2", value="100nF", P1=v3v3, P2=gnd)
Capacitor(name="C3", value="10uF",  P1=v3v3, P2=gnd)

# Reset
Resistor( name="R_RST", value="10k",   P1=v3v3,    P2=n_reset)
Capacitor(name="C_RST", value="100nF", P1=n_reset, P2=gnd)

# Debug
SWD(vcc=v3v3, gnd=gnd, swdio=Net("SWDIO"), swclk=Net("SWCLK"),
    swo=Net("SWO"), nreset=n_reset)

# Status LED
StatusLED(gpio=Net("LED_GPIO"), vcc=v3v3, gnd=gnd)
```
"""


# ── Public API ────────────────────────────────────────────────────────────────

def generate(description: str, error_feedback: str | None = None) -> str:
    """
    Call Claude to generate a .zen board file for the given NL description.

    Args:
        description:    Plain-English project description.
        error_feedback: Optional `pcb build` error output from a previous
                        attempt — triggers a self-healing retry.

    Returns:
        Raw .zen file content (no markdown fences).
    """
    client = anthropic.Anthropic()

    messages: list[dict] = []

    if error_feedback:
        # Self-healing: show Claude the previous attempt and its build error
        messages.append({
            "role": "user",
            "content": (
                f"Generate a Zener board file for: {description}\n\n"
                "Your previous attempt failed `pcb build` with these errors:\n"
                f"```\n{error_feedback}\n```\n\n"
                "Fix all errors and output only corrected .zen code."
            ),
        })
    else:
        messages.append({
            "role": "user",
            "content": f"Generate a Zener board file for: {description}",
        })

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    raw = response.content[0].text.strip()

    # Strip accidental markdown fences if Claude includes them
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        )

    return raw.strip()
