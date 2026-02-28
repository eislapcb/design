'use strict';

/**
 * Eisla — Eurocircuits Adapter (server/fabadapters/eurocircuits.js)
 *
 * EU-based pooling fab. No public API — rate card only (as of 2026-02).
 * Currency: EUR. Assembly: available.
 *
 * If API access is confirmed in future, add a live quote path here
 * and change method from 'rate_card' to 'api_live'.
 */

const path = require('path');
const { getQuote } = require('./rate-card-engine');

const RATE_CARD = require(path.join(__dirname, '..', '..', 'data', 'fab_rates', 'eurocircuits.json'));

/**
 * quote(boardSpec)
 * Returns raw quote in EUR (no margin applied).
 */
function quote(boardSpec) {
  return getQuote(RATE_CARD, boardSpec);
}

module.exports = { quote, RATE_CARD };
