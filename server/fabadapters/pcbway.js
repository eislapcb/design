'use strict';

/**
 * Eisla — PCBWay Adapter (server/fabadapters/pcbway.js)
 *
 * Chinese fab with dynamic pricing. No API — rate card only.
 * Currency: USD. Assembly: available.
 */

const path = require('path');
const { getQuote } = require('./rate-card-engine');

const RATE_CARD = require(path.join(__dirname, '..', '..', 'data', 'fab_rates', 'pcbway.json'));

/**
 * quote(boardSpec)
 * Returns raw quote in USD (no margin applied).
 */
function quote(boardSpec) {
  return getQuote(RATE_CARD, boardSpec);
}

module.exports = { quote, RATE_CARD };
