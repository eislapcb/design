'use strict';

/**
 * Eisla — Fab Quoter (server/fabquoter.js)
 *
 * Sessions 14-16. Orchestrates all four fab adapters in parallel,
 * converts to GBP, applies margin, and writes fab_quotes.json.
 *
 * Called by worker.js after post-processing (files_ready stage).
 * Uses Promise.allSettled so one fab failure never blocks the others.
 *
 * FX rates: read from Redis (fx:USD_GBP, fx:EUR_GBP) with hardcoded
 * fallbacks. Updated daily by cron (see BRIEF.md).
 */

const fs   = require('fs');
const path = require('path');

const pcbtrain    = require('./fabadapters/pcbtrain');
const pcbway      = require('./fabadapters/pcbway');
const eurocircuits = require('./fabadapters/eurocircuits');
const jlcpcb      = require('./fabadapters/jlcpcb');
const { applyMargin, getManufacturingMargin } = require('./pricing');

// ─── FX rates ────────────────────────────────────────────────────────────────

const FX_FALLBACKS = {
  USD_GBP: 0.79,
  EUR_GBP: 0.855,
  GBP_GBP: 1.0,
};

async function getFxRate(fromCurrency) {
  if (fromCurrency === 'GBP') return 1.0;

  const key = `${fromCurrency}_GBP`;

  // Try Redis first
  try {
    const IORedis = require('ioredis');
    const redis = new IORedis(process.env.REDIS_URL || 'redis://localhost:6379', {
      maxRetriesPerRequest: 1,
      connectTimeout: 2000,
    });
    const val = await redis.get(`fx:${key}`);
    await redis.quit();
    if (val) return parseFloat(val);
  } catch {
    // Redis unavailable — use fallback
  }

  return FX_FALLBACKS[key] || 1.0;
}

// ─── Convert raw quote to GBP with margin ────────────────────────────────────

function convertQuote(rawQuote, fxRate, jobType, boardSpec) {
  const quotesGbp = {};

  for (const [qtyStr, rawPrice] of Object.entries(rawQuote.quotes)) {
    const qty     = parseInt(qtyStr, 10);
    const rawGbp  = round2(rawPrice * fxRate);
    const custGbp = applyMargin(rawGbp, jobType, qty);

    quotesGbp[qty] = {
      raw_gbp:      rawGbp,
      customer_gbp: custGbp,
      lead_days:    rawQuote.lead_days,
    };
  }

  return {
    fab:                rawQuote.fab,
    method:             rawQuote.method,
    currency_raw:       rawQuote.currency,
    fx_rate_to_gbp:     fxRate,
    quotes:             quotesGbp,
    assembly_available: rawQuote.assembly_available,
    note:               rawQuote.note,
    url:                rawQuote.url,
    rate_card_date:     rawQuote.rate_card_date || null,
    gerber_file_id:     rawQuote.gerber_file_id || null,
  };
}

// ─── Main: get all quotes ────────────────────────────────────────────────────

/**
 * getAllQuotes(boardSpec, jobDir, options)
 *
 * boardSpec: { dimensions_mm, layers, surface_finish, copper_weight_oz }
 * jobDir:    path to job directory (for Gerber ZIP)
 * options:   { jobType: 'new' | 'reorder' }
 *
 * Returns the fab_quotes object and writes fab_quotes.json to jobDir.
 */
async function getAllQuotes(boardSpec, jobDir, { jobType = 'new' } = {}) {
  const gerberZip = path.join(jobDir, 'output.zip');

  // Fire all four adapters in parallel
  const results = await Promise.allSettled([
    pcbtrain.quote(boardSpec),
    pcbway.quote(boardSpec),
    eurocircuits.quote(boardSpec),
    jlcpcb.quote(boardSpec, gerberZip),
  ]);

  const fabNames = ['PCBTrain', 'PCBWay', 'Eurocircuits', 'JLCPCB'];
  const quotes = [];

  for (let i = 0; i < results.length; i++) {
    const r = results[i];
    if (r.status === 'rejected') {
      console.warn(`[fabquoter] ${fabNames[i]} failed: ${r.reason?.message || r.reason}`);
      continue;
    }

    const rawQuote = r.value;
    if (!rawQuote || !rawQuote.quotes || Object.keys(rawQuote.quotes).length === 0) {
      console.warn(`[fabquoter] ${fabNames[i]} returned no quotes`);
      continue;
    }

    const fxRate = await getFxRate(rawQuote.currency);
    quotes.push(convertQuote(rawQuote, fxRate, jobType, boardSpec));
  }

  const output = {
    generated_at: new Date().toISOString(),
    board_spec:   boardSpec,
    job_type:     jobType,
    quotes,
  };

  // Write to disk
  const outPath = path.join(jobDir, 'fab_quotes.json');
  fs.writeFileSync(outPath, JSON.stringify(output, null, 2), 'utf8');
  console.log(`[fabquoter] ${quotes.length} fab quote(s) written to fab_quotes.json`);

  return output;
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

module.exports = { getAllQuotes };
