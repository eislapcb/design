'use strict';

/**
 * Eisla — Pricing (server/pricing.js)
 *
 * Design fee tiers, manufacturing margin, repeat discount.
 * All env-overridable so margins can be adjusted without a deploy.
 *
 * BRIEF.md pricing rules:
 *   Tier 1 (£499) — ATmega, STM32F0/F1/F3, ESP8266. Repeat: £449.
 *   Tier 2 (£599) — ESP32, RP2040, nRF52840, STM32F4. Repeat: £539.
 *   Tier 3 (£749) — STM32H7, i.MX RT. Repeat: £674.
 *   Promo  (£299) — Selected partners only. Not a standard tier.
 *   Manufacturing margin: 26% new, 13% reorder. Reduces at volume.
 *   Never expose raw fab prices via the API.
 */

// ─── Constants (env-overridable) ─────────────────────────────────────────────

const MARGIN_RATE         = parseFloat(process.env.MARGIN_RATE          || '0.26');
const REORDER_MARGIN_RATE = parseFloat(process.env.REORDER_MARGIN_RATE  || '0.13');
const REPEAT_DISCOUNT_RATE = parseFloat(process.env.REPEAT_DISCOUNT_RATE || '0.10');
const PROMO_FEE_GBP       = parseInt(process.env.PROMO_DESIGN_FEE       || '299', 10);

// ─── Design fee tiers ─────────────────────────────────────────────────────────

const TIERS = {
  1: {
    fee_gbp:        499,
    repeat_fee_gbp: 449,
    label:          'Tier 1',
    mcu_examples:   'ATmega, STM32F0/F1/F3, ESP8266',
    engineer_review: false,
  },
  2: {
    fee_gbp:        599,
    repeat_fee_gbp: 539,
    label:          'Tier 2',
    mcu_examples:   'ESP32, RP2040, nRF52840, STM32F4',
    engineer_review: true,
    review_hours:   4,
  },
  3: {
    fee_gbp:        749,
    repeat_fee_gbp: 674,
    label:          'Tier 3',
    mcu_examples:   'STM32H7, i.MX RT (LQFP only)',
    engineer_review: true,
    review_hours:   6,
  },
};

// ─── Design fee ───────────────────────────────────────────────────────────────

/**
 * getDesignFee(tier, options)
 *
 * Returns the design fee in pence (integer GBP × 100) for Stripe.
 * options: { repeat_customer?: bool, promo?: bool }
 */
function getDesignFee(tier, { repeat_customer = false, promo = false } = {}) {
  if (promo) return PROMO_FEE_GBP * 100; // pence

  const t = TIERS[tier];
  if (!t) throw new Error(`Unknown pricing tier: ${tier}`);

  const fee_gbp = repeat_customer ? t.repeat_fee_gbp : t.fee_gbp;
  return fee_gbp * 100; // pence for Stripe
}

/**
 * getDesignFeeGbp(tier, options)
 *
 * Same as getDesignFee but returns GBP (float) for display.
 */
function getDesignFeeGbp(tier, options = {}) {
  return getDesignFee(tier, options) / 100;
}

// ─── Manufacturing margin ─────────────────────────────────────────────────────

/**
 * getManufacturingMargin(jobType, quantity)
 *
 * Returns the margin rate (e.g. 0.26) for a given job type and quantity.
 * jobType: 'new' | 'reorder'
 */
function getManufacturingMargin(jobType, quantity) {
  if (jobType === 'reorder') return REORDER_MARGIN_RATE; // flat 13%
  // New design — volume taper
  if (quantity >= 100) return 0.13;
  if (quantity >= 50)  return 0.18;
  if (quantity >= 20)  return 0.22;
  return MARGIN_RATE; // 0.26 (1–19 boards)
}

/**
 * applyMargin(rawPriceGbp, jobType, quantity)
 *
 * Returns the customer-facing price in GBP (2 d.p.).
 * IMPORTANT: raw price must NEVER be exposed via the API.
 */
function applyMargin(rawPriceGbp, jobType, quantity) {
  const rate = getManufacturingMargin(jobType, quantity);
  return Math.round(rawPriceGbp * (1 + rate) * 100) / 100;
}

/**
 * applyMarginPence(rawPricePence, jobType, quantity)
 *
 * Same but in pence (integer) for Stripe.
 */
function applyMarginPence(rawPricePence, jobType, quantity) {
  const rate = getManufacturingMargin(jobType, quantity);
  return Math.round(rawPricePence * (1 + rate));
}

// ─── Service level surcharges ─────────────────────────────────────────────────

const SERVICE_LEVELS = {
  standard: { label: 'Standard',  surcharge_gbp: 0   },
  priority: { label: 'Priority',  surcharge_gbp: 50  },
  express:  { label: 'Express',   surcharge_gbp: 150 },
};

/**
 * getServiceSurchargePence(serviceLevel)
 */
function getServiceSurchargePence(serviceLevel) {
  const s = SERVICE_LEVELS[serviceLevel];
  if (!s) throw new Error(`Unknown service level: ${serviceLevel}`);
  return s.surcharge_gbp * 100; // pence
}

// ─── Exports ──────────────────────────────────────────────────────────────────

module.exports = {
  TIERS,
  SERVICE_LEVELS,
  MARGIN_RATE,
  REORDER_MARGIN_RATE,
  REPEAT_DISCOUNT_RATE,
  PROMO_FEE_GBP,
  getDesignFee,
  getDesignFeeGbp,
  getManufacturingMargin,
  applyMargin,
  applyMarginPence,
  getServiceSurchargePence,
};
