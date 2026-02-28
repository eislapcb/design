'use strict';

/**
 * Eisla — Rate Card Pricing Engine (server/fabadapters/rate-card-engine.js)
 *
 * Shared engine for PCBTrain, PCBWay, and Eurocircuits adapters.
 * All three use the same model: linear area interpolation from a reference
 * price table, with multipliers for layers, surface finish, and copper weight.
 *
 * Input: board spec + rate card JSON → raw price in the fab's native currency.
 * FX conversion and margin are applied upstream (fabquoter.js).
 */

// ─── Standard quantity breakpoints ───────────────────────────────────────────

const STANDARD_QTYS = [5, 10, 25, 50, 100];

// ─── Area interpolation ─────────────────────────────────────────────────────

/**
 * Interpolate a price from the rate card entries by board area.
 *
 * For a given quantity key (e.g. 'qty_10'), finds the two entries whose
 * area_cm2 brackets the target area and linearly interpolates. If the
 * target area is below the smallest entry, uses the smallest. If above
 * the largest, extrapolates linearly.
 */
function interpolateByArea(entries, areaCm2, qtyKey) {
  // Sort by area ascending (should already be, but defensive)
  const sorted = [...entries].sort((a, b) => a.area_cm2 - b.area_cm2);

  // Below smallest entry — use the smallest price
  if (areaCm2 <= sorted[0].area_cm2) {
    return sorted[0][qtyKey] ?? null;
  }

  // Above largest entry — extrapolate from last two
  const last = sorted[sorted.length - 1];
  if (areaCm2 >= last.area_cm2) {
    const prev = sorted[sorted.length - 2];
    const pricePerCm2 = (last[qtyKey] - prev[qtyKey]) / (last.area_cm2 - prev.area_cm2);
    return last[qtyKey] + pricePerCm2 * (areaCm2 - last.area_cm2);
  }

  // Find bracketing entries and interpolate
  for (let i = 0; i < sorted.length - 1; i++) {
    const lo = sorted[i];
    const hi = sorted[i + 1];
    if (areaCm2 >= lo.area_cm2 && areaCm2 <= hi.area_cm2) {
      const t = (areaCm2 - lo.area_cm2) / (hi.area_cm2 - lo.area_cm2);
      return lo[qtyKey] + t * (hi[qtyKey] - lo[qtyKey]);
    }
  }

  return null;
}

// ─── Quote from rate card ────────────────────────────────────────────────────

/**
 * getQuote(rateCard, boardSpec)
 *
 * boardSpec: {
 *   dimensions_mm: [w, h],
 *   layers:         number,
 *   surface_finish: string (optional — uses default),
 *   copper_weight_oz: number (optional — default 1),
 * }
 *
 * Returns: {
 *   fab:         string,
 *   method:      'rate_card',
 *   currency:    string (native),
 *   quotes:      { [qty]: price_native },  // raw price in native currency
 *   lead_days:   number,
 *   assembly_available: bool,
 *   note:        string,
 *   url:         string,
 * }
 */
function getQuote(rateCard, boardSpec) {
  const [w, h] = boardSpec.dimensions_mm || [100, 80];
  const areaCm2 = (w * h) / 100; // mm² → cm²

  const layers = boardSpec.layers || 2;
  const finish = boardSpec.surface_finish || Object.keys(rateCard.surface_finishes)[0];
  const copperOz = boardSpec.copper_weight_oz || 1;

  const entries = rateCard.price_table.entries;

  // Layer multiplier
  const layerMult = rateCard.layer_multipliers[String(layers)] || 1;

  // Copper weight multiplier
  const copperKey = `${copperOz}oz`;
  const copperMult = (rateCard.copper_weight_multipliers || {})[copperKey] || 1;

  // Surface finish surcharge
  const finishSpec = rateCard.surface_finishes[finish] || {};
  const finishPct = finishSpec.surcharge_pct || 0;
  const finishFlat = finishSpec.surcharge_gbp_flat
    || finishSpec.surcharge_usd_flat
    || finishSpec.surcharge_eur_flat
    || 0;

  // Calculate prices for each standard quantity
  const quotes = {};
  for (const qty of STANDARD_QTYS) {
    const qtyKey = `qty_${qty}`;
    const basePrice = interpolateByArea(entries, areaCm2, qtyKey);
    if (basePrice == null) continue;

    // Apply multipliers: layer → copper → finish
    let price = basePrice * layerMult * copperMult;
    price = price * (1 + finishPct) + finishFlat;
    quotes[qty] = round2(price);
  }

  // Lead time
  const leadDays = rateCard.lead_times.standard_days
    || rateCard.lead_times.pool_standard_days
    || 10;

  return {
    fab:                rateCard._meta.fab,
    method:             'rate_card',
    currency:           rateCard._meta.currency,
    quotes,
    lead_days:          leadDays,
    assembly_available: rateCard.assembly_available || false,
    note:               rateCard._meta.note || '',
    url:                rateCard._meta.url || '',
    rate_card_date:     rateCard._meta.rate_card_date,
  };
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

module.exports = { getQuote, interpolateByArea, STANDARD_QTYS };
