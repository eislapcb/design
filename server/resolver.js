'use strict';

/**
 * Eisla — Capability Resolver (server/resolver.js)
 *
 * Takes a set of capability selections and board constraints, returns a
 * concrete component list with warnings, power budget, layer recommendation,
 * and design price tier.
 *
 * Follows the 8-step process defined in BRIEF.md.
 */

const fs   = require('fs');
const path = require('path');

// ─── Data loading ────────────────────────────────────────────────────────────

const DATA_DIR = path.join(__dirname, '..', 'data');

let _components  = null;
let _capabilities = null;

function getComponents() {
  if (!_components) {
    _components = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'components.json'), 'utf8'));
  }
  return _components;
}

function getCapabilities() {
  if (!_capabilities) {
    _capabilities = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'capabilities.json'), 'utf8'));
  }
  return _capabilities;
}

// ─── Design price tiers (from BRIEF.md) ──────────────────────────────────────

const PRICE_TIERS = {
  1: { fee_gbp: 499, repeat_fee_gbp: 449 },
  2: { fee_gbp: 599, repeat_fee_gbp: 539 },
  3: { fee_gbp: 749, repeat_fee_gbp: 674 },
};

// ─── Capability companions ───────────────────────────────────────────────────
// Components that must accompany a capability but won't be picked by the greedy
// matcher (because the capability is already resolved by a higher-scored component).

const CAPABILITY_COMPANIONS = {
  power_lipo: 'jst_ph_2pin',     // LiPo battery connector
  rtc:        'cr2032_holder',    // Coin cell backup for RTC
  ethernet:   'hr911105a',        // Ethernet magnetics + RJ45
};

// Map decoupling cap value strings to component IDs
const DECOUPLING_MAP = {
  '100nF': 'cap_100nf_0402',
  '10uF':  'cap_10uf_0805',
  '4.7uF': 'cap_10uf_0805',
  '1uF':   'cap_100nf_0402',
  '22uF':  'cap_10uf_0805',
};

// ─── Conflict detection rules ─────────────────────────────────────────────────

const CONFLICT_RULES = [
  {
    caps: ['lora', 'wifi'],
    level: 'warn',
    message: 'High RF complexity — keep LoRa and WiFi transmissions non-simultaneous to avoid interference',
  },
  {
    caps: ['power_lipo', 'power_mains'],
    level: 'warn',
    message: 'Clarify power architecture — do you want mains to charge the LiPo, or dual independent power inputs?',
  },
  {
    caps: ['low_power_sleep', 'display_oled'],
    level: 'info',
    message: 'Displays prevent deep sleep — the board will wake briefly to update the display then return to sleep',
  },
  {
    caps: ['low_power_sleep', 'display_tft'],
    level: 'info',
    message: 'Displays prevent deep sleep — the board will wake briefly to update the display then return to sleep',
  },
  {
    caps: ['motor_dc', 'sense_temperature'],
    level: 'info',
    message: 'Motor switching noise can interfere with sensitive sensors — placement rules will enforce separation',
  },
  {
    caps: ['motor_stepper', 'sense_temperature'],
    level: 'info',
    message: 'Motor switching noise can interfere with sensitive sensors — placement rules will enforce separation',
  },
];

// ─── Power source limits ──────────────────────────────────────────────────────

const POWER_LIMITS = {
  power_usb:   { max_ma: 500, warn_ma: 400, label: 'USB 5V' },
  power_lipo:  { max_ma: null, warn_ma: null, label: 'LiPo battery' },
  power_aa:    { max_ma: 300, warn_ma: 200, label: 'AA batteries' },
  power_mains: { max_ma: null, warn_ma: null, label: 'Mains/DC jack' },
  power_solar: { max_ma: null, warn_ma: null, label: 'Solar panel' },
};

const LIPO_TYPICAL_MAH = 1000; // used for runtime estimate

// ─── Helpers ─────────────────────────────────────────────────────────────────

function scoreComponent(comp, capabilities) {
  let score = 0;
  for (const cap of capabilities) {
    score += (comp.capability_score && comp.capability_score[cap]) || 0;
  }
  return score;
}

function capabilitiesSatisfiedBy(comp) {
  return comp.capabilities || [];
}

// ─── Main resolve function ────────────────────────────────────────────────────

/**
 * Resolve a capability selection into a concrete component list.
 *
 * @param {object} input
 * @param {string[]} input.capabilities   - Array of capability IDs
 * @param {object}  input.board           - { layers, dimensions_mm, power_source }
 * @param {boolean} [input.repeat_customer] - Apply repeat discount to price
 * @returns {object} Resolution result (see BRIEF.md Step 8 schema)
 */
function resolve(input) {
  const { capabilities: rawCaps = [], board = {}, repeat_customer = false } = input;

  const components   = getComponents();
  const allCompList  = Object.values(components);
  const warnings     = [];

  // Normalise capabilities to unique lowercase set
  const selectedCaps = [...new Set(rawCaps.map(c => c.toLowerCase().trim()))];

  // Track which capabilities are still unresolved
  const unresolved = new Set(selectedCaps);
  const resolved   = [];   // { component_id, quantity, satisfies[], auto_added, reason? }

  // ── Step 1: Normalise ──────────────────────────────────────────────────────
  // (done above — unique, lowercase, trimmed)

  // ── Step 2: Find and select MCU ───────────────────────────────────────────
  const processingCaps = selectedCaps.filter(c =>
    ['processing_basic', 'processing_standard', 'processing_powerful'].includes(c)
  );

  // Default to processing_standard if nothing specified but wifi/ble selected
  // (basic MCUs can't handle WiFi — auto-upgrade per spec)
  let effectiveProcTier = processingCaps.includes('processing_powerful') ? 'processing_powerful'
    : processingCaps.includes('processing_standard')                     ? 'processing_standard'
    : processingCaps.includes('processing_basic')                        ? 'processing_basic'
    : null;

  if (effectiveProcTier === 'processing_basic' && selectedCaps.includes('wifi')) {
    warnings.push({
      level: 'warn',
      message: 'Basic MCU cannot handle WiFi — automatically upgrading to standard processing tier',
    });
    effectiveProcTier = 'processing_standard';
    unresolved.delete('processing_basic');
    unresolved.add('processing_standard');
  }

  let selectedMcu = null;

  if (effectiveProcTier || selectedCaps.length > 0) {
    const mcuCandidates = allCompList.filter(c => c.satisfies_processing === true);

    // Score each MCU against all selected capabilities
    const scored = mcuCandidates.map(comp => ({
      comp,
      score: scoreComponent(comp, selectedCaps),
    }));

    // Sort: highest score first; break ties by cost (cheaper wins)
    scored.sort((a, b) => b.score - a.score || (a.comp.cost_gbp_unit || 999) - (b.comp.cost_gbp_unit || 999));

    // Filter to minimum processing tier requested
    const tierOrder = { processing_basic: 1, processing_standard: 2, processing_powerful: 3 };
    const minTier = tierOrder[effectiveProcTier] || 1;

    const eligible = scored.filter(({ comp }) => {
      if (!comp.capabilities) return false;
      const compMaxTier = Math.max(
        ...comp.capabilities
          .filter(c => tierOrder[c])
          .map(c => tierOrder[c]),
        0
      );
      return compMaxTier >= minTier;
    });

    if (eligible.length > 0) {
      selectedMcu = eligible[0].comp;

      // Mark all capabilities the MCU satisfies as resolved
      const mcuSatisfies = capabilitiesSatisfiedBy(selectedMcu).filter(c => unresolved.has(c));
      for (const cap of mcuSatisfies) unresolved.delete(cap);

      resolved.push({
        component_id: selectedMcu.id,
        quantity: 1,
        satisfies: mcuSatisfies,
        auto_added: false,
        display_name: selectedMcu.display_name,
        category: selectedMcu.category,
        cost_gbp_unit: selectedMcu.cost_gbp_unit || 0,
        power_consumption_ma: selectedMcu.power_consumption_ma || 0,
      });

      if (mcuSatisfies.length > 1) {
        warnings.push({
          level: 'info',
          message: `${selectedMcu.display_name} satisfies ${mcuSatisfies.join(', ')} — no separate modules needed for these`,
        });
      }
    }
  }

  // ── Step 3: Resolve remaining capabilities ────────────────────────────────
  const remaining = [...unresolved].filter(c =>
    !['processing_basic', 'processing_standard', 'processing_powerful'].includes(c)
  );

  // Build a list of components that satisfy at least one remaining capability
  // Try to find components that satisfy multiple remaining caps at once (preferred)
  const alreadyUsed = new Set(resolved.map(r => r.component_id));

  // Sort remaining so caps with fewer matching components are resolved first
  const stillUnresolved = new Set(remaining);

  while (stillUnresolved.size > 0) {
    // Find best component for the remaining set
    const candidates = allCompList.filter(comp => {
      if (alreadyUsed.has(comp.id)) return false;
      return (comp.capabilities || []).some(c => stillUnresolved.has(c));
    });

    if (candidates.length === 0) {
      // Nothing in the DB for these capabilities
      for (const cap of stillUnresolved) {
        warnings.push({ level: 'warn', message: `No component found in database for capability: ${cap}` });
      }
      break;
    }

    // Score each candidate against only the still-unresolved caps
    const unresArr = [...stillUnresolved];
    const scored = candidates.map(comp => {
      const satisfies = (comp.capabilities || []).filter(c => stillUnresolved.has(c));
      return {
        comp,
        satisfies,
        score: scoreComponent(comp, unresArr),
        cost: comp.cost_gbp_unit || 999,
      };
    });

    // Prefer: most caps satisfied first, then highest score, then cheapest
    scored.sort((a, b) =>
      b.satisfies.length - a.satisfies.length ||
      b.score - a.score ||
      a.cost - b.cost
    );

    const best = scored[0];
    alreadyUsed.add(best.comp.id);

    for (const cap of best.satisfies) stillUnresolved.delete(cap);

    resolved.push({
      component_id: best.comp.id,
      quantity: 1,
      satisfies: best.satisfies,
      auto_added: false,
      display_name: best.comp.display_name,
      category: best.comp.category,
      cost_gbp_unit: best.comp.cost_gbp_unit || 0,
      power_consumption_ma: best.comp.power_consumption_ma || 0,
    });
  }

  // ── Step 4: Infer supporting components (data-driven) ────────────────────
  const powerCaps = selectedCaps.filter(c => Object.keys(POWER_LIMITS).includes(c));

  // Helper to push an auto-added component
  // force=true bypasses dedup (used by auto_add_components where duplicates are intentional,
  // e.g. USB-C needs 2× res_5k1_0402 for CC1+CC2, ATmega needs 2× cap_22pf for crystal)
  function autoAdd(compId, reason, force = false) {
    if (!force && alreadyUsed.has(compId)) return false;
    const comp = components[compId];
    if (!comp) {
      warnings.push({ level: 'info', message: `Auto-add component '${compId}' not found in database` });
      return false;
    }
    resolved.push({
      component_id: comp.id,
      quantity: 1,
      satisfies: [],
      auto_added: true,
      reason,
      display_name: comp.display_name,
      category: comp.category,
      cost_gbp_unit: comp.cost_gbp_unit || 0,
      power_consumption_ma: comp.power_consumption_ma || 0,
    });
    alreadyUsed.add(comp.id);
    return true;
  }

  // 4a. Capability companions — components that must accompany a capability
  for (const [cap, compId] of Object.entries(CAPABILITY_COMPANIONS)) {
    if (!selectedCaps.includes(cap)) continue;
    const comp = components[compId];
    autoAdd(compId, (comp && comp.auto_add_note) || `Required companion for ${cap}`);
  }

  // 4b. Process auto_add_components from all resolved components
  // force=true: honour duplicate entries (e.g. 2× crystal load caps, 2× CC pull-downs)
  const resolvedSnapshot = [...resolved];
  for (const entry of resolvedSnapshot) {
    const comp = components[entry.component_id];
    if (!comp || !Array.isArray(comp.auto_add_components)) continue;
    for (const addId of comp.auto_add_components) {
      autoAdd(addId, comp.auto_add_note || `Required by ${comp.display_name || comp.id}`, true);
    }
  }

  // 4c. Decoupling caps for ICs with requires_decoupling: true
  for (const entry of resolved) {
    const comp = components[entry.component_id];
    if (!comp || !comp.requires_decoupling || !Array.isArray(comp.decoupling_caps)) continue;
    for (const dc of comp.decoupling_caps) {
      const capId = DECOUPLING_MAP[dc.value] || 'cap_100nf_0402';
      const capComp = components[capId];
      if (!capComp) continue;
      // Each VDD pin gets its own cap — don't deduplicate
      resolved.push({
        component_id: capComp.id,
        quantity: 1,
        satisfies: [],
        auto_added: true,
        reason: `Decoupling for ${comp.display_name || comp.id} pin ${dc.pin || 'VDD'}`,
        display_name: capComp.display_name,
        category: capComp.category,
        cost_gbp_unit: capComp.cost_gbp_unit || 0,
        power_consumption_ma: 0,
      });
    }
  }

  // 4d. I2C bus pull-ups (one shared pair per bus)
  const hasI2C = resolved.some(entry => {
    const comp = components[entry.component_id];
    return comp && Array.isArray(comp.interfaces) && comp.interfaces.includes('I2C');
  });
  if (hasI2C) {
    const pullup = components['res_4k7_0402'];
    if (pullup) {
      for (const line of ['SDA', 'SCL']) {
        resolved.push({
          component_id: pullup.id,
          quantity: 1,
          satisfies: [],
          auto_added: true,
          reason: `I2C ${line} pull-up (4.7k, shared across bus)`,
          display_name: pullup.display_name,
          category: pullup.category,
          cost_gbp_unit: pullup.cost_gbp_unit || 0,
          power_consumption_ma: 0,
        });
      }
    }
  }

  // ── Step 5: Power budget ───────────────────────────────────────────────────
  const totalMa = resolved.reduce((sum, r) => sum + (r.power_consumption_ma || 0), 0);

  // Determine power source
  const powerSource = powerCaps.find(c => Object.keys(POWER_LIMITS).includes(c)) || 'power_usb';
  const limit = POWER_LIMITS[powerSource];

  const powerBudget = {
    total_ma: totalMa,
    source: powerSource,
    source_label: limit.label,
    headroom_ma: limit.max_ma ? limit.max_ma - totalMa : null,
    estimated_runtime_hours:
      powerSource === 'power_lipo' && totalMa > 0
        ? Math.round((LIPO_TYPICAL_MAH / totalMa) * 10) / 10
        : null,
  };

  if (limit.warn_ma && totalMa > limit.warn_ma) {
    warnings.push({
      level: totalMa > (limit.max_ma || Infinity) ? 'warn' : 'info',
      message: `Total current draw is ${totalMa}mA — ${
        totalMa > (limit.max_ma || Infinity)
          ? `exceeds ${limit.label} capacity of ${limit.max_ma}mA`
          : `approaching ${limit.label} limit of ${limit.max_ma}mA (${limit.max_ma - totalMa}mA headroom)`
      }`,
    });
  }

  if (powerSource === 'power_aa' && totalMa > 200) {
    warnings.push({
      level: 'warn',
      message: `AA batteries with ${totalMa}mA draw will exhaust quickly — consider USB or LiPo power instead`,
    });
  }

  // ── Step 6: Conflict detection ────────────────────────────────────────────
  for (const rule of CONFLICT_RULES) {
    if (rule.caps.every(c => selectedCaps.includes(c))) {
      warnings.push({ level: rule.level, message: rule.message });
    }
  }

  // ── Step 7: Layer recommendation ──────────────────────────────────────────
  // All Eisla boards are 4-layer as standard (BRIEF.md §Pricing).
  const recommendedLayers = 4;

  // ── Step 8: Pricing ───────────────────────────────────────────────────────
  const mcuTier = selectedMcu?.tier || 1;
  const tierPricing = PRICE_TIERS[mcuTier] || PRICE_TIERS[1];
  const designFeeGbp = repeat_customer ? tierPricing.repeat_fee_gbp : tierPricing.fee_gbp;

  // Estimated BOM cost (components only, not manufacturing)
  const bomCostGbp = resolved.reduce((sum, r) => sum + (r.cost_gbp_unit || 0) * r.quantity, 0);

  return {
    resolved_components: resolved,
    warnings,
    power_budget: powerBudget,
    recommended_layers: recommendedLayers,
    mcu: selectedMcu ? { id: selectedMcu.id, display_name: selectedMcu.display_name, tier: mcuTier } : null,
    pricing: {
      tier: mcuTier,
      design_fee_gbp: designFeeGbp,
      repeat_customer,
      bom_cost_estimate_gbp: Math.round(bomCostGbp * 100) / 100,
    },
  };
}

// ─── Module export ────────────────────────────────────────────────────────────

module.exports = { resolve };

// ─── CLI test (node server/resolver.js) ───────────────────────────────────────

if (require.main === module) {
  const testCases = [
    {
      label: 'Soil moisture sensor (WiFi + LiPo + temperature)',
      input: {
        capabilities: ['wifi', 'bluetooth', 'processing_standard', 'sense_temperature', 'sense_humidity', 'power_lipo', 'low_power_sleep'],
        board: { layers: 2, dimensions_mm: [80, 60] },
      },
    },
    {
      label: 'Simple Arduino-style project (basic MCU, USB power)',
      input: {
        capabilities: ['processing_basic', 'led_single', 'buttons', 'power_usb'],
        board: { layers: 2 },
      },
    },
    {
      label: 'Motor controller (DC motors + WiFi)',
      input: {
        capabilities: ['wifi', 'processing_standard', 'motor_dc', 'motor_dc', 'power_usb'],
        board: { layers: 2 },
      },
    },
  ];

  for (const tc of testCases) {
    console.log('\n' + '='.repeat(70));
    console.log('TEST:', tc.label);
    console.log('='.repeat(70));
    const result = resolve(tc.input);
    console.log('\nComponents resolved:', result.resolved_components.length);
    for (const r of result.resolved_components) {
      const auto = r.auto_added ? ' [auto]' : '';
      console.log(`  ${r.display_name || r.component_id}${auto} — satisfies: [${r.satisfies.join(', ')}]`);
    }
    console.log('\nWarnings:');
    for (const w of result.warnings) {
      console.log(`  [${w.level.toUpperCase()}] ${w.message}`);
    }
    console.log('\nPower budget:', result.power_budget.total_ma + 'mA', '|', result.power_budget.source_label);
    if (result.power_budget.estimated_runtime_hours) {
      console.log('  Estimated runtime:', result.power_budget.estimated_runtime_hours + 'h (1000mAh cell)');
    }
    console.log('Layers recommended:', result.recommended_layers);
    console.log('Design fee: £' + result.pricing.design_fee_gbp, '(Tier ' + result.pricing.tier + ')');
    console.log('BOM estimate: £' + result.pricing.bom_cost_estimate_gbp);
  }
}
