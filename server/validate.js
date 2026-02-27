#!/usr/bin/env node
/**
 * Eisla — Session 1 Data Validation Script
 * 
 * Validates capabilities.json and components.json against the brief's
 * required schema, cross-references, and sanity checks.
 * 
 * Usage: node validate.js [--fix] [--verbose]
 *   --fix      Auto-fix trivial issues (empty arrays, missing defaults)
 *   --verbose  Show passing checks too (default: errors/warnings only)
 * 
 * Exit code 0 = all clear, 1 = errors found
 */

const fs = require('fs');
const path = require('path');

// --- CLI flags ---
const args = process.argv.slice(2);
const FIX = args.includes('--fix');
const VERBOSE = args.includes('--verbose');

// --- Load data ---
const DATA_DIR = __dirname;
const capsPath = path.join(DATA_DIR, 'capabilities.json');
const compsPath = path.join(DATA_DIR, 'components.json');

let caps, comps;
try {
  caps = JSON.parse(fs.readFileSync(capsPath, 'utf8'));
} catch (e) {
  console.error('FATAL: Cannot read capabilities.json:', e.message);
  process.exit(1);
}
try {
  comps = JSON.parse(fs.readFileSync(compsPath, 'utf8'));
} catch (e) {
  console.error('FATAL: Cannot read components.json:', e.message);
  process.exit(1);
}

// --- Counters ---
let errors = 0;
let warnings = 0;
let passes = 0;
let fixes = 0;

function error(msg) { errors++; console.log(`  ✗ ERROR: ${msg}`); }
function warn(msg) { warnings++; console.log(`  ⚠ WARN:  ${msg}`); }
function pass(msg) { passes++; if (VERBOSE) console.log(`  ✓ ${msg}`); }
function fix(msg) { fixes++; console.log(`  🔧 FIX:  ${msg}`); }
function section(title) { console.log(`\n${'='.repeat(60)}\n${title}\n${'='.repeat(60)}`); }

// ============================================================
// 1. CAPABILITIES.JSON STRUCTURE
// ============================================================
section('1. CAPABILITIES.JSON STRUCTURE');

const validGroups = ['connectivity', 'processing', 'sensing', 'power', 'output', 'ui', 'storage'];
const capList = caps.capabilities || [];
const capIds = new Set();
const capRequiredFields = ['id', 'display_label', 'group'];

if (!Array.isArray(capList) || capList.length === 0) {
  error('capabilities.json has no capabilities array');
} else {
  pass(`capabilities array has ${capList.length} entries`);
}

capList.forEach((cap, i) => {
  // Required fields
  capRequiredFields.forEach(f => {
    if (cap[f] === undefined || cap[f] === null || cap[f] === '') {
      error(`Capability [${i}] missing required field: ${f}`);
    }
  });

  // Duplicate ID check
  if (capIds.has(cap.id)) {
    error(`Duplicate capability ID: ${cap.id}`);
  }
  capIds.add(cap.id);

  // Valid group
  if (cap.group && !validGroups.includes(cap.group)) {
    error(`Capability ${cap.id} has invalid group: ${cap.group} (valid: ${validGroups.join(', ')})`);
  }

  // ID format: lowercase, underscores only
  if (cap.id && !/^[a-z][a-z0-9_]*$/.test(cap.id)) {
    warn(`Capability ID ${cap.id} should be lowercase_snake_case`);
  }
});

pass(`${capIds.size} unique capability IDs`);

// Brief-required capabilities (lines 300-372)
const briefCaps = [
  'wifi', 'bluetooth', 'lora', 'zigbee', 'can_bus', 'ethernet', 'usb_device', 'usb_host', 'uart',
  'processing_basic', 'processing_standard', 'processing_powerful',
  'sense_temperature', 'sense_humidity', 'sense_motion_imu', 'sense_proximity', 'sense_light',
  'sense_gas', 'sense_pressure', 'sense_gps', 'sense_camera', 'adc_external',
  'power_usb', 'power_lipo', 'power_aa', 'power_mains', 'power_solar', 'low_power_sleep',
  'motor_dc', 'motor_stepper', 'motor_servo', 'relay', 'led_single', 'led_rgb_strip', 'speaker_buzzer',
  'display_oled', 'display_lcd', 'display_tft', 'buttons', 'touch', 'rotary_encoder',
  'storage_sd', 'storage_flash', 'rtc', 'eeprom'
];

briefCaps.forEach(id => {
  if (capIds.has(id)) {
    pass(`Brief capability ${id} present`);
  } else {
    error(`Brief-REQUIRED capability MISSING: ${id}`);
  }
});

// ============================================================
// 2. COMPONENTS.JSON SCHEMA — all brief-required fields
// ============================================================
section('2. COMPONENTS.JSON SCHEMA FIELDS');

const compIds = Object.keys(comps);

if (compIds.length === 0) {
  error('components.json is empty');
}
pass(`${compIds.length} components loaded`);

// Fields from brief example (lines 251-285) + additional brief references
const requiredFields = [
  { name: 'id',                    type: 'string' },
  { name: 'display_name',         type: 'string' },
  { name: 'category',             type: 'string' },
  { name: 'subcategory',          type: 'string' },
  { name: 'kicad_footprint',      type: 'string' },
  { name: 'kicad_symbol',         type: 'string' },   // brief line 1293
  { name: 'dimensions_mm',        type: 'object' },
  { name: 'courtyard_clearance_mm', type: 'number' },
  { name: 'placement_zone',       type: 'string' },
  { name: 'placement_priority',   type: 'number' },
  { name: 'antenna_keepout_mm',   type: 'number' },
  { name: 'decoupling_caps',      type: 'array' },
  { name: 'requires_decoupling',  type: 'boolean' },   // brief line 2062
  { name: 'min_layers',           type: 'number' },
  { name: 'power_consumption_ma', type: 'number' },
  { name: 'supply_voltage',       type: 'string' },
  { name: 'interfaces',           type: 'array' },
  { name: 'digikey_pn',           type: 'string' },
  { name: 'mpn',                  type: 'string' },
  { name: 'lcsc_pn',              type: 'string' },    // brief line 2408, 2623
  { name: 'datasheet_url',        type: 'string' },
  { name: 'ipc610_notes',         type: 'string' },
  { name: 'capabilities',         type: 'array' },
  { name: 'capability_score',     type: 'object' },
  { name: 'satisfies_processing', type: 'boolean' },
  { name: 'cost_gbp_unit',        type: 'number' },
];

const validCategories = ['mcu', 'power', 'sensor', 'comms', 'display', 'motor_driver', 'passive', 'connector'];
const validPlacementZones = ['edge_top', 'edge_bottom', 'edge_left', 'edge_right', 'centre', 'power_column', 'any', 'corner'];

// Per-field missing count
const fieldMissing = {};
requiredFields.forEach(f => { fieldMissing[f.name] = []; });

compIds.forEach(id => {
  const comp = comps[id];

  requiredFields.forEach(f => {
    const val = comp[f.name];
    if (val === undefined || val === null) {
      fieldMissing[f.name].push(id);
    } else {
      // Type check
      if (f.type === 'string' && typeof val !== 'string') {
        warn(`${id}.${f.name} should be string, got ${typeof val}`);
      }
      if (f.type === 'number' && typeof val !== 'number') {
        warn(`${id}.${f.name} should be number, got ${typeof val}`);
      }
      if (f.type === 'boolean' && typeof val !== 'boolean') {
        warn(`${id}.${f.name} should be boolean, got ${typeof val}`);
      }
      if (f.type === 'array' && !Array.isArray(val)) {
        warn(`${id}.${f.name} should be array, got ${typeof val}`);
      }
      if (f.type === 'object' && (typeof val !== 'object' || Array.isArray(val))) {
        warn(`${id}.${f.name} should be object, got ${typeof val}`);
      }
    }
  });
});

// Report
requiredFields.forEach(f => {
  const missing = fieldMissing[f.name];
  if (missing.length === 0) {
    pass(`${f.name} — present on all ${compIds.length} components`);
  } else {
    error(`${f.name} — MISSING on ${missing.length} components: ${missing.slice(0, 5).join(', ')}${missing.length > 5 ? '...' : ''}`);
  }
});

// ============================================================
// 3. COMPONENT ID CONSISTENCY
// ============================================================
section('3. COMPONENT ID CONSISTENCY');

const duplicateIds = [];
const idSet = new Set();
compIds.forEach(id => {
  if (comps[id].id !== id) {
    error(`Component key "${id}" does not match its .id field "${comps[id].id}"`);
  }
  if (idSet.has(id)) {
    duplicateIds.push(id);
  }
  idSet.add(id);
});

if (duplicateIds.length === 0) {
  pass('No duplicate component IDs');
} else {
  error(`Duplicate component IDs: ${duplicateIds.join(', ')}`);
}

// ID format
compIds.forEach(id => {
  if (!/^[a-z][a-z0-9_]*$/.test(id)) {
    warn(`Component ID ${id} should be lowercase_snake_case`);
  }
});

// ============================================================
// 4. CATEGORY / PLACEMENT ZONE VALIDATION
// ============================================================
section('4. CATEGORY & PLACEMENT ZONE VALIDATION');

compIds.forEach(id => {
  const c = comps[id];
  if (c.category && !validCategories.includes(c.category)) {
    error(`${id} has invalid category: "${c.category}" (valid: ${validCategories.join(', ')})`);
  }
  if (c.placement_zone && !validPlacementZones.includes(c.placement_zone)) {
    warn(`${id} has non-standard placement_zone: "${c.placement_zone}"`);
  }
});

pass('Category/placement zone check complete');

// ============================================================
// 5. CAPABILITY CROSS-REFERENCES
// ============================================================
section('5. CAPABILITY CROSS-REFERENCES');

// 5a. Orphan capability refs (components reference caps that don't exist)
const orphanRefs = [];
compIds.forEach(id => {
  const c = comps[id];
  (c.capabilities || []).forEach(cap => {
    if (!capIds.has(cap)) orphanRefs.push(`${id}.capabilities → "${cap}"`);
  });
  Object.keys(c.capability_score || {}).forEach(cap => {
    if (!capIds.has(cap)) orphanRefs.push(`${id}.capability_score → "${cap}"`);
  });
});

if (orphanRefs.length === 0) {
  pass('No orphan capability references');
} else {
  orphanRefs.forEach(ref => error(`Orphan capability ref: ${ref}`));
}

// 5b. Uncovered capabilities (caps with no component that satisfies them)
const coveredCaps = new Set();
compIds.forEach(id => {
  (comps[id].capabilities || []).forEach(cap => coveredCaps.add(cap));
});

const uncovered = [...capIds].filter(id => !coveredCaps.has(id));
if (uncovered.length === 0) {
  pass('All capabilities have at least one component');
} else {
  uncovered.forEach(id => error(`Capability "${id}" has NO component that satisfies it`));
}

// 5c. capability_score keys must be subset of capabilities array
compIds.forEach(id => {
  const c = comps[id];
  const capSet = new Set(c.capabilities || []);
  Object.keys(c.capability_score || {}).forEach(scoreKey => {
    if (!capSet.has(scoreKey)) {
      warn(`${id}: capability_score has "${scoreKey}" but capabilities array doesn't include it`);
    }
  });
});

// ============================================================
// 6. MCU-SPECIFIC CHECKS
// ============================================================
section('6. MCU-SPECIFIC CHECKS');

const mcus = compIds.filter(id => comps[id].category === 'mcu');
pass(`${mcus.length} MCUs found`);

mcus.forEach(id => {
  const c = comps[id];

  // Must have tier field (brief line 476)
  if (c.tier === undefined) {
    error(`MCU ${id} missing "tier" field (required for pricing.js)`);
  } else if (![1, 2, 3].includes(c.tier)) {
    error(`MCU ${id} has invalid tier: ${c.tier} (must be 1, 2, or 3)`);
  } else {
    pass(`MCU ${id} tier = ${c.tier}`);
  }

  // Must have satisfies_processing: true
  if (c.satisfies_processing !== true) {
    error(`MCU ${id} must have satisfies_processing: true`);
  }

  // Must have at least one processing capability
  const processingCaps = (c.capabilities || []).filter(cap => cap.startsWith('processing_'));
  if (processingCaps.length === 0) {
    error(`MCU ${id} has no processing_* capability`);
  }

  // Must have power_consumption_ma > 0
  if (c.power_consumption_ma <= 0) {
    error(`MCU ${id} has power_consumption_ma = ${c.power_consumption_ma} (must be > 0)`);
  }

  // Should have kicad_symbol
  if (!c.kicad_symbol || c.kicad_symbol === 'N/A') {
    warn(`MCU ${id} has no valid kicad_symbol`);
  }
});

// ============================================================
// 7. POWER CONSUMPTION SANITY CHECKS
// ============================================================
section('7. POWER CONSUMPTION SANITY CHECKS');

// Active ICs should have power > 0
const activeCategories = ['mcu', 'sensor', 'comms', 'display', 'motor_driver'];
const suspiciousZeroPower = compIds.filter(id => {
  const c = comps[id];
  return activeCategories.includes(c.category) && c.power_consumption_ma === 0;
});

if (suspiciousZeroPower.length === 0) {
  pass('All active ICs have power_consumption_ma > 0');
} else {
  suspiciousZeroPower.forEach(id => {
    // Power regulators are an exception — they're in 'power' category
    warn(`Active component ${id} (${comps[id].category}) has power_consumption_ma = 0`);
  });
}

// Passives and connectors should have power = 0 or very low
compIds.filter(id => ['passive', 'connector'].includes(comps[id].category)).forEach(id => {
  if (comps[id].power_consumption_ma > 20) {
    warn(`${id} is ${comps[id].category} but draws ${comps[id].power_consumption_ma}mA — verify`);
  }
});

// No negative power values
compIds.forEach(id => {
  if (comps[id].power_consumption_ma < 0) {
    error(`${id} has negative power_consumption_ma`);
  }
});

pass('Power consumption sanity check complete');

// ============================================================
// 8. COST SANITY CHECKS
// ============================================================
section('8. COST SANITY CHECKS');

// Free components (fiducials, mounting holes, test point footprints) are OK at 0
const allowedFreeCats = ['fiducial', 'mounting', 'test_point'];
compIds.forEach(id => {
  const c = comps[id];
  if (c.cost_gbp_unit < 0) {
    error(`${id} has negative cost: £${c.cost_gbp_unit}`);
  }
  if (c.cost_gbp_unit === 0 && !allowedFreeCats.some(cat => (c.subcategory || '').includes(cat))) {
    // Just a warning — some footprint-only items are legitimately free
    if (c.category !== 'passive' || c.power_consumption_ma > 0) {
      warn(`${id} has cost = £0.00 — verify this is intentional`);
    }
  }
  if (c.cost_gbp_unit > 20) {
    warn(`${id} costs £${c.cost_gbp_unit.toFixed(2)} — unusually expensive, verify`);
  }
});

pass('Cost sanity check complete');

// ============================================================
// 9. LCSC PART NUMBER CHECK
// ============================================================
section('9. LCSC PART NUMBERS (JLCPCB Assembly)');

// All SMT components should have LCSC PN for JLCPCB assembly
const smtCategories = ['mcu', 'sensor', 'comms', 'display', 'motor_driver', 'power'];
const missingLcsc = compIds.filter(id => {
  const c = comps[id];
  return smtCategories.includes(c.category) && (!c.lcsc_pn || c.lcsc_pn === 'N/A' || c.lcsc_pn === '');
});

if (missingLcsc.length === 0) {
  pass('All SMT active components have LCSC part numbers');
} else {
  missingLcsc.forEach(id => warn(`SMT component ${id} missing lcsc_pn (needed for JLCPCB assembly)`));
}

// Passives — check format (should be C followed by digits)
const badLcscFormat = compIds.filter(id => {
  const pn = comps[id].lcsc_pn;
  return pn && pn !== 'N/A' && !/^C\d+$/.test(pn);
});

if (badLcscFormat.length === 0) {
  pass('All LCSC PNs follow C-number format');
} else {
  badLcscFormat.forEach(id => warn(`${id} has non-standard LCSC PN: "${comps[id].lcsc_pn}" (expected Cxxxxx)`));
}

// ============================================================
// 10. KiCad FOOTPRINT / SYMBOL CHECKS
// ============================================================
section('10. KiCad FOOTPRINT & SYMBOL CHECKS');

compIds.forEach(id => {
  const c = comps[id];

  if (!c.kicad_footprint || c.kicad_footprint === '') {
    error(`${id} has empty kicad_footprint`);
  }

  if (!c.kicad_symbol || c.kicad_symbol === '') {
    error(`${id} has empty kicad_symbol`);
  }

  // Footprint should contain a colon (Library:Footprint format)
  if (c.kicad_footprint && !c.kicad_footprint.includes(':') && c.kicad_footprint !== 'N/A') {
    warn(`${id} kicad_footprint "${c.kicad_footprint}" missing library prefix (expected Library:Footprint)`);
  }
});

pass('KiCad symbol/footprint check complete');

// ============================================================
// 11. DECOUPLING CAP STRUCTURE VALIDATION
// ============================================================
section('11. DECOUPLING CAP VALIDATION');

compIds.forEach(id => {
  const c = comps[id];

  // If requires_decoupling is true, decoupling_caps should be non-empty
  if (c.requires_decoupling === true && (!c.decoupling_caps || c.decoupling_caps.length === 0)) {
    error(`${id} has requires_decoupling: true but empty decoupling_caps array`);
  }

  // If decoupling_caps is non-empty, requires_decoupling should be true
  if (c.decoupling_caps && c.decoupling_caps.length > 0 && c.requires_decoupling !== true) {
    warn(`${id} has decoupling_caps but requires_decoupling is not true`);
  }

  // Validate decoupling cap entries
  (c.decoupling_caps || []).forEach((cap, i) => {
    if (!cap.value) warn(`${id}.decoupling_caps[${i}] missing "value"`);
    if (!cap.package) warn(`${id}.decoupling_caps[${i}] missing "package"`);
    if (!cap.pin) warn(`${id}.decoupling_caps[${i}] missing "pin"`);
    if (typeof cap.max_distance_mm !== 'number') warn(`${id}.decoupling_caps[${i}] missing/invalid "max_distance_mm"`);
  });
});

pass('Decoupling cap validation complete');

// ============================================================
// 12. DIMENSIONS VALIDATION
// ============================================================
section('12. DIMENSIONS VALIDATION');

compIds.forEach(id => {
  const dims = comps[id].dimensions_mm;
  if (!dims) return; // Already caught by field check

  if (typeof dims.width !== 'number' || dims.width <= 0) {
    error(`${id}.dimensions_mm.width invalid: ${dims.width}`);
  }
  if (typeof dims.height !== 'number' || dims.height <= 0) {
    error(`${id}.dimensions_mm.height invalid: ${dims.height}`);
  }

  // Sanity: no component > 100mm
  if (dims.width > 100 || dims.height > 100) {
    warn(`${id} dimensions ${dims.width}×${dims.height}mm — unusually large, verify`);
  }
});

pass('Dimensions validation complete');

// ============================================================
// 13. AUTO-ADD RULE VALIDATION
// ============================================================
section('13. AUTO-ADD RULES');

const knownRules = new Set([
  'resolver_auto_add_always',
  'resolver_auto_add_usb',
  'resolver_auto_add_lipo',
  'resolver_auto_add_barrel_jack',
  'resolver_auto_add_esp32_rp2040',
  'resolver_auto_add_mcu_atmega328p',
  'resolver_auto_add_mcu_rp2040',
  'resolver_auto_add_mcu_nrf52840',
  'resolver_auto_add_mcu_stm32',
  'resolver_auto_add_mcu_rtc_crystal',
  'resolver_auto_add_crystal',
  'resolver_auto_add_arm',
  'resolver_auto_add_avr',
  'resolver_auto_add_rs485',
  'resolver_auto_add_rs232',
  'resolver_auto_add_can',
  'resolver_auto_add_bus_termination',
  'resolver_auto_add_i2c',
  'resolver_auto_add_i2c_display',
  'resolver_auto_add_tft_display',
  'resolver_auto_add_lcd_display',
  'resolver_auto_add_motor',
  'resolver_auto_add_led_strip',
  'resolver_auto_add_mmwave',
  'resolver_auto_add_load_cell',
  'resolver_auto_add_soil',
  'resolver_auto_add_0_10v',
  'resolver_auto_add_gps',
  'resolver_auto_add_camera',
  'resolver_auto_add_adc',
  'resolver_auto_add_uart_needed',
  'resolver_auto_add_rf_antenna',
  'resolver_auto_add_5v_input',
  'resolver_auto_add_5v_boost',
  'resolver_auto_add_5v_level_divider',
  'resolver_auto_add_power_aa_solar',
  'resolver_auto_add_power_input',
  'resolver_auto_add_power_rail',
  'resolver_auto_add_servo',
  'resolver_auto_add_relay',
  'resolver_auto_add_industrial_bus',
  'resolver_auto_add_cellular',
  'resolver_auto_add_switching_power',
  'resolver_auto_add_analog_power_isolation',
  'resolver_auto_add_mains',
  'resolver_auto_add_usb_lipo',
  'resolver_auto_add',  // generic
  'resolver_auto_add_per_vdd_pin',
  'resolver_auto_add_i2c_conflict',
  'resolver_auto_add_i2c_level_shift',
  'resolver_auto_add_buck_converter',
  'resolver_auto_add_buck_3v3',
  'resolver_auto_add_buck_5v',
  'resolver_auto_add_adc_protection',
]);

const autoAdds = compIds.filter(id => comps[id].auto_add_rule);
pass(`${autoAdds.length} components have auto_add_rule`);

const unknownRules = [];
autoAdds.forEach(id => {
  const rule = comps[id].auto_add_rule;
  if (!knownRules.has(rule)) {
    unknownRules.push(`${id}: "${rule}"`);
  }
});

if (unknownRules.length === 0) {
  pass('All auto_add_rules are recognised');
} else {
  unknownRules.forEach(r => warn(`Unknown auto_add_rule: ${r} (add to resolver or validate.js knownRules)`));
}

// ============================================================
// 14. POWER SOURCE & POWER MODES (extended fields)
// ============================================================
section('14. POWER SOURCE & POWER MODES (extended)');

const powerComps = compIds.filter(id => comps[id].category === 'power');
const withPowerSource = powerComps.filter(id => comps[id].power_source);
const withoutPowerSource = powerComps.filter(id => !comps[id].power_source && 
  !['battery_protection'].includes(comps[id].subcategory)); // DW01A/FS8205A exempt

if (withPowerSource.length > 0) {
  pass(`${withPowerSource.length} power components have power_source spec`);
  withPowerSource.forEach(id => {
    const ps = comps[id].power_source;
    if (!ps.max_output_current_ma) warn(`${id}.power_source missing max_output_current_ma`);
    if (!ps.output_rail) warn(`${id}.power_source missing output_rail`);
  });
}
if (withoutPowerSource.length > 0) {
  withoutPowerSource.forEach(id => warn(`Power component ${id} missing power_source spec`));
}

const withPowerModes = compIds.filter(id => comps[id].power_modes);
pass(`${withPowerModes.length} components have power_modes`);

withPowerModes.forEach(id => {
  const pm = comps[id].power_modes;
  if (pm.peak_current_ma === undefined) warn(`${id}.power_modes missing peak_current_ma`);
  if (pm.typical_active_ma === undefined) warn(`${id}.power_modes missing typical_active_ma`);
});

// MCUs should have power_modes for resolver power budget
mcus.forEach(id => {
  if (!comps[id].power_modes) {
    warn(`MCU ${id} missing power_modes (needed for battery life estimation)`);
  }
});

// ============================================================
// 15. SAFETY WARNINGS (extended)
// ============================================================
section('15. SAFETY WARNINGS (extended)');

const withSafety = compIds.filter(id => comps[id].safety_warnings && comps[id].safety_warnings.length > 0);
pass(`${withSafety.length} components have safety_warnings`);

// Check that dangerous components have warnings
const dangerousComponents = compIds.filter(id => {
  const c = comps[id];
  return c.display_name && (
    c.display_name.toLowerCase().includes('mains') ||
    c.display_name.toLowerCase().includes('relay') ||
    c.display_name.toLowerCase().includes('lipo') ||
    c.display_name.toLowerCase().includes('tp4056') ||
    (c.id && c.id.includes('hlk_pm')) ||
    (c.max_voltage_rating && c.max_voltage_rating >= 50)
  );
});

dangerousComponents.forEach(id => {
  if (!comps[id].safety_warnings || comps[id].safety_warnings.length === 0) {
    warn(`${id} (${comps[id].display_name}) appears safety-critical but has no safety_warnings`);
  }
});

// ============================================================
// 16. SUPPLEMENTARY DATA FILES
// ============================================================
section('16. SUPPLEMENTARY DATA FILES');

const supplementaryFiles = [
  'safety_disclaimer.json',
  'power_budget_model.json',
];

supplementaryFiles.forEach(f => {
  const fpath = path.join(DATA_DIR, f);
  if (fs.existsSync(fpath)) {
    try {
      JSON.parse(fs.readFileSync(fpath, 'utf8'));
      pass(`${f} exists and is valid JSON`);
    } catch (e) {
      error(`${f} exists but is NOT valid JSON: ${e.message}`);
    }
  } else {
    warn(`${f} not found (optional but recommended)`);
  }
});

// ============================================================
// FINAL REPORT
// ============================================================
section('VALIDATION REPORT');

console.log(`
  Capabilities:  ${capIds.size}
  Components:    ${compIds.length}
  Auto-add:      ${autoAdds.length}
  
  ✓ Passed:     ${passes}
  ⚠ Warnings:   ${warnings}
  ✗ Errors:      ${errors}
  ${FIX ? `🔧 Fixes:      ${fixes}` : ''}
`);

if (errors === 0) {
  console.log('  ✅ VALIDATION PASSED — Session 1 data is ready for resolver development.\n');
} else {
  console.log('  ❌ VALIDATION FAILED — fix errors before proceeding to Session 2.\n');
}

process.exit(errors > 0 ? 1 : 0);
