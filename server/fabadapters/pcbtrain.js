'use strict';

/**
 * Eisla — PCBTrain Adapter (server/fabadapters/pcbtrain.js)
 *
 * UK-based pooling fab. No API — rate card only.
 * Currency: GBP. Assembly: not available.
 */

const path = require('path');
const { getQuote } = require('./rate-card-engine');

const RATE_CARD = require(path.join(__dirname, '..', '..', 'data', 'fab_rates', 'pcbtrain.json'));

/**
 * quote(boardSpec)
 * Returns raw quote in GBP (no margin applied).
 */
function quote(boardSpec) {
  return getQuote(RATE_CARD, boardSpec);
}

module.exports = { quote, RATE_CARD };
