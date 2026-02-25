#!/usr/bin/env node
/**
 * check_component.js — Pre-flight validator for a single component.
 * Usage: node check_component.js <component_id>
 * 
 * Checks one component against all schema requirements BEFORE you run
 * the full validate.js. Catches the common mistakes immediately.
 */

const fs = require('fs');
const comps = JSON.parse(fs.readFileSync('components.json'));
const capsData = JSON.parse(fs.readFileSync('capabilities.json'));
const caps = capsData.capabilities || capsData;
const capIds = Array.isArray(caps) ? caps.map(c => c.id) : Object.keys(caps);

const id = process.argv[2];
if (!id) {
  console.log('Usage: node check_component.js <component_id>');
  console.log('Available IDs (last 10 added):');
  Object.keys(comps).slice(-10).forEach(k => console.log('  ' + k));
  process.exit(1);
}

const c = comps[id];
if (!c) {
  console.log(`❌ Component "${id}" not found in components.json`);
  console.log('Did you mean: ' + Object.keys(comps).filter(k => k.includes(id)).join(', '));
  process.exit(1);
}

let errors = 0, warnings = 0;
const err = (msg) => { errors++; console.log(`  ✗ ERROR: ${msg}`); };
const warn = (msg) => { warnings++; console.log(`  ⚠ WARN:  ${msg}`); };
const pass = (msg) => { console.log(`  ✓ ${msg}`); };

console.log(`\nChecking: ${id} (${c.display_name || 'NO NAME'})`);
console.log('='.repeat(60));

// === REQUIRED FIELDS ===
console.log('\n--- Required Fields ---');
const requiredStr = ['id', 'display_name', 'category', 'subcategory', 'kicad_footprint', 'kicad_symbol', 'mpn', 'ref_designator_prefix', 'supply_voltage'];
const requiredNum = ['courtyard_clearance_mm', 'placement_priority', 'antenna_keepout_mm', 'min_layers', 'power_consumption_ma', 'cost_gbp_unit'];
const requiredBool = ['requires_decoupling', 'satisfies_processing'];
const requiredArr = ['capabilities', 'interfaces', 'decoupling_caps'];
const requiredObj = ['dimensions_mm', 'capability_score', 'pins'];

requiredStr.forEach(f => {
  if (c[f] === undefined || c[f] === null) err(`Missing required string field: ${f}`);
  else if (typeof c[f] !== 'string') err(`${f} should be string, got ${typeof c[f]}`);
  else pass(`${f}: "${c[f]}"`);
});

requiredNum.forEach(f => {
  if (c[f] === undefined || c[f] === null) err(`Missing required number field: ${f}`);
  else if (typeof c[f] !== 'number') err(`${f} should be number, got ${typeof c[f]} ("${c[f]}")`);
  else pass(`${f}: ${c[f]}`);
});

requiredBool.forEach(f => {
  if (c[f] === undefined || c[f] === null) err(`Missing required boolean field: ${f}`);
  else if (typeof c[f] !== 'boolean') err(`${f} should be boolean, got ${typeof c[f]}`);
  else pass(`${f}: ${c[f]}`);
});

requiredArr.forEach(f => {
  if (!Array.isArray(c[f])) err(`${f} should be array, got ${typeof c[f]}`);
  else pass(`${f}: [${c[f].length} items]`);
});

requiredObj.forEach(f => {
  if (typeof c[f] !== 'object' || c[f] === null || Array.isArray(c[f])) err(`${f} should be object, got ${Array.isArray(c[f]) ? 'array' : typeof c[f]}`);
  else pass(`${f}: {${Object.keys(c[f]).length} keys}`);
});

// === ID MATCH ===
console.log('\n--- ID Consistency ---');
if (c.id !== id) err(`id field "${c.id}" doesn't match object key "${id}"`);
else pass(`id matches key: ${id}`);

if (!/^[a-z0-9_]+$/.test(id)) warn(`id "${id}" should be lowercase_snake_case`);
else pass('id is lowercase_snake_case');

// === CATEGORY VALIDATION ===
console.log('\n--- Category ---');
const validCats = ['mcu', 'power', 'sensor', 'comms', 'display', 'motor_driver', 'passive', 'connector'];
if (!validCats.includes(c.category)) err(`Invalid category "${c.category}". Valid: ${validCats.join(', ')}`);
else pass(`category: ${c.category}`);

// === PLACEMENT ZONE ===
const validZones = ['centre', 'edge_top', 'edge_bottom', 'edge_left', 'edge_right', 'any', 'corner'];
if (c.placement_zone && !validZones.includes(c.placement_zone)) warn(`Non-standard placement_zone: "${c.placement_zone}". Standard: ${validZones.join(', ')}`);

// === MIN LAYERS ===
if (c.min_layers !== 4) err(`min_layers is ${c.min_layers}, should be 4 (all boards are 4-layer)`);

// === CAPABILITIES ===
console.log('\n--- Capabilities ---');
if (Array.isArray(c.capabilities)) {
  c.capabilities.forEach(cap => {
    if (!capIds.includes(cap)) err(`Orphan capability: "${cap}" not in capabilities.json`);
    else pass(`capability: ${cap}`);
  });
  // Check capability_score matches
  if (typeof c.capability_score === 'object' && !Array.isArray(c.capability_score)) {
    Object.keys(c.capability_score).forEach(k => {
      if (!c.capabilities.includes(k)) warn(`capability_score has "${k}" but it's not in capabilities array`);
    });
  }
}

// === DECOUPLING CAPS FORMAT ===
console.log('\n--- Decoupling Caps ---');
if (Array.isArray(c.decoupling_caps) && c.decoupling_caps.length > 0) {
  c.decoupling_caps.forEach((cap, i) => {
    if (typeof cap === 'string') err(`decoupling_caps[${i}] is a string "${cap}" — must be object {value, package, pin, max_distance_mm}`);
    else {
      if (!cap.value) warn(`decoupling_caps[${i}] missing "value"`);
      if (!cap.package) warn(`decoupling_caps[${i}] missing "package"`);
      if (!cap.pin) warn(`decoupling_caps[${i}] missing "pin"`);
      if (!cap.max_distance_mm) warn(`decoupling_caps[${i}] missing "max_distance_mm"`);
      if (cap.value && cap.package && cap.pin && cap.max_distance_mm) pass(`decoupling_caps[${i}]: ${cap.value} ${cap.package} on ${cap.pin} within ${cap.max_distance_mm}mm`);
    }
  });
} else if (c.requires_decoupling) {
  warn('requires_decoupling is true but decoupling_caps is empty');
}

// === POWER MODES ===
console.log('\n--- Power Modes ---');
if (c.power_modes) {
  if (!c.power_modes.typical_active_ma && c.power_modes.typical_active_ma !== 0) warn('power_modes missing typical_active_ma');
  else pass(`typical_active_ma: ${c.power_modes.typical_active_ma}`);
  if (!c.power_modes.peak_current_ma && c.power_modes.peak_current_ma !== 0) warn('power_modes missing peak_current_ma');
  else pass(`peak_current_ma: ${c.power_modes.peak_current_ma}`);
} else if (c.category !== 'passive' && c.category !== 'connector') {
  warn('No power_modes — should have active/sleep/peak data for active ICs');
}

// === PINS ===
console.log('\n--- Pins ---');
if (c.pins) {
  if (!c.pins.count) warn('pins.count missing');
  else pass(`pin count: ${c.pins.count}`);
  
  if (c.pins.interfaces && typeof c.pins.interfaces === 'object') {
    if (c.pins.interfaces.I2C) {
      if (!c.pins.interfaces.I2C.address) warn('I2C device missing address');
      else pass(`I2C address: ${c.pins.interfaces.I2C.address}`);
    }
  }
}

// === LCSC ===
console.log('\n--- Procurement ---');
if (c.lcsc_part_number) pass(`LCSC: ${c.lcsc_part_number}`);
else warn('Missing lcsc_part_number');
if (c.lcsc_pn) {
  if (c.lcsc_part_number && c.lcsc_pn !== c.lcsc_part_number) warn(`lcsc_pn "${c.lcsc_pn}" doesn't match lcsc_part_number "${c.lcsc_part_number}"`);
  else pass('lcsc_pn matches');
} else warn('Missing lcsc_pn');

// === AUTO-ADD ===
if (c.auto_add_rule) {
  console.log('\n--- Auto-Add ---');
  pass(`auto_add_rule: ${c.auto_add_rule}`);
  if (c.auto_add_components) {
    c.auto_add_components.forEach(aid => {
      if (!comps[aid]) err(`auto_add_components references "${aid}" which doesn't exist`);
      else pass(`auto_adds: ${aid}`);
    });
  }
}

// === DIMENSIONS ===
if (c.dimensions_mm) {
  const d = c.dimensions_mm;
  if (!d.length && !d.width) warn('dimensions_mm missing length/width');
}

// === DATASHEET ===
if (!c.datasheet_url && c.datasheet_url !== '') warn('Missing datasheet_url');
else if (c.datasheet_url === '') warn('datasheet_url is empty — populate before production');

// === SUMMARY ===
console.log('\n' + '='.repeat(60));
console.log(`  ✓ Passed checks`);
console.log(`  ⚠ Warnings: ${warnings}`);
console.log(`  ✗ Errors:   ${errors}`);
if (errors === 0) console.log('\n  ✅ Component is valid. Run `node validate.js` for full database check.');
else console.log('\n  ❌ Fix errors before proceeding.');
console.log('');
