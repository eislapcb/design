# Adding Components to Eisla

## Process Overview

Every component in `components.json` must have 34 validated fields, a verified pinout, and correct cross-references to `capabilities.json`. This document defines the process to ensure nothing is missed.

## Step 1: Gather Data

Before touching any JSON, collect these from the **datasheet**:

| Data | Source | Notes |
|---|---|---|
| Full part number (MPN) | Datasheet front page | Must be orderable, not generic family name |
| Package & dimensions | Datasheet mechanical drawing | Length × width × height in mm |
| Pin count & pinout | Datasheet pin configuration table | Every pin: number, name, function |
| Supply voltage range | Datasheet electrical characteristics | Min/typical/max VDD |
| Current consumption | Datasheet electrical characteristics | Active, sleep, and peak current |
| Interfaces | Datasheet features/block diagram | I2C address, SPI mode, UART baud etc. |
| Thermal info | Datasheet thermal characteristics | θJA, exposed pad, max junction temp |
| Recommended circuit | Datasheet application circuit | Required external components |

Then from **LCSC/supplier**:

| Data | Source |
|---|---|
| LCSC C-number | lcsc.com search by MPN |
| JLCPCB basic/extended | JLCPCB parts library |
| Unit cost (GBP) | LCSC pricing at qty 10 |

Then from **KiCad**:

| Data | Source |
|---|---|
| Footprint path | KiCad footprint browser — must exist in standard library |
| Symbol path | KiCad symbol browser — must exist in standard library |

## Step 2: Create Component Entry

Copy the structure from `component_template.json` into `components.json` as a new keyed object.

**Key naming**: `lowercase_snake_case`, derived from part name. Examples:
- BME680 → `bme680`
- AMS1117-3.3 → `ams1117_3v3`
- TCA9548A → `tca9548a`
- 10kΩ 0402 resistor → `res_10k_0402`
- 100nF 0402 cap → `cap_100nf_0402`

**Critical field rules**:

- `id` must exactly match the object key
- `category` must be one of: `mcu`, `power`, `sensor`, `comms`, `display`, `motor_driver`, `passive`, `connector`
- `placement_priority` is a **number** (1-10), not a string
- `capability_score` is an **object** `{cap_id: score}`, not a number
- `decoupling_caps` is an array of **objects** `[{value, package, pin, max_distance_mm}]`, not strings
- `capabilities` array entries must exist in `capabilities.json`
- `min_layers` is always `4`
- `power_modes` must include `typical_active_ma` and `peak_current_ma` at top level

## Step 3: Verify Pinout

The pinout in `pins` must be verified against the datasheet:

1. Open the datasheet to the pin configuration table
2. Verify every pin number, name, and function matches
3. For ICs with exposed/thermal pads: include as a pin
4. For I2C devices: record address AND alt_address
5. For devices with configurable pins (ADDR, SDO): document both states
6. Cross-check pin count matches package (e.g., TQFP-32 = 32 pins)

## Step 4: Set Auto-Add Rules

Determine if this component:

**Is auto-added by another component?**
→ Set `auto_add_rule` to the triggering rule name (must be in `validate.js` knownRules)

**Triggers auto-adding of other components?**
→ Set `auto_add_components` array with the IDs of components to add
→ Set `auto_add_note` explaining the chain

Common auto-add patterns:
- IC with I2C → needs pull-up resistors (if not already on bus)
- IC with crystal → needs crystal + load caps
- Motor driver → needs bulk cap + TVS on VMOT
- USB connector → needs ESD protection + CC pull-downs
- Battery connector → needs charger + protection ICs
- Any IC → needs 100nF decoupling per VDD pin

## Step 5: Check Capabilities

If the component provides a capability not yet in `capabilities.json`:

1. Add the capability to `capabilities.json` → `capabilities` array
2. Required fields: `id`, `display_label`, `group` (one of: connectivity, processing, sensing, power, output, ui, storage)
3. Update the component's `capabilities` array to reference the new capability ID
4. Update `capability_score` with scores for each capability

## Step 6: Validate

```bash
node validate.js
```

Must show:
- **0 errors** — any errors must be fixed before merging
- Component count increased by the number of components added
- No new warnings related to the added components

## Step 7: Checklist

Before considering the component complete, verify:

- [ ] `id` matches object key, lowercase_snake_case
- [ ] `category` is a valid enum value
- [ ] `ref_designator_prefix` set correctly per silkscreen_rules.json
- [ ] `kicad_footprint` exists in KiCad 7+ standard libraries
- [ ] `kicad_symbol` exists in KiCad 7+ standard libraries
- [ ] `dimensions_mm` has length, width, height from datasheet mechanical drawing
- [ ] `placement_priority` is a number 1-10
- [ ] `capability_score` is an object, not a number
- [ ] `decoupling_caps` is array of objects with value/package/pin/max_distance_mm
- [ ] `min_layers` is 4
- [ ] `supply_voltage` matches datasheet
- [ ] `power_consumption_ma` matches datasheet typical active
- [ ] `power_modes` has active, sleep (if applicable), typical_active_ma, peak_current_ma
- [ ] `pins` verified against datasheet — every pin accounted for
- [ ] `pins.interfaces.I2C.address` set for I2C devices
- [ ] `lcsc_part_number` and `lcsc_pn` both set and matching
- [ ] `capabilities` entries exist in capabilities.json
- [ ] `auto_add_rule` in validate.js knownRules (if set)
- [ ] `auto_add_components` IDs exist in components.json (if set)
- [ ] `node validate.js` returns 0 errors

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| `placement_priority: "medium"` | Warning: should be number | Use `5` not `"medium"` |
| `capability_score: 50` | Warning: should be object | Use `{"cap_id": 5}` |
| `decoupling_caps: ["100nF"]` | Warning: missing value/package/pin | Use `[{value:"100nF", package:"0402", pin:"VDD", max_distance_mm:3}]` |
| Missing `id` field | Error: MISSING | Must match object key |
| `category: "ic"` | Error: invalid category | Use `comms`, `sensor`, etc. |
| Capability not in capabilities.json | Error: orphan capability ref | Add to capabilities.json first |
| `min_layers: 2` | Silent — but wrong | Always `4` |
