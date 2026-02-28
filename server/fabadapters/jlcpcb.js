'use strict';

/**
 * Eisla — JLCPCB Adapter (server/fabadapters/jlcpcb.js)
 *
 * Session 15. Full JLCPCB adapter with live API + rate card fallback.
 *
 * Flow:
 *   1. Upload Gerber ZIP → gerber_file_id
 *   2. Pre-review → parsed dimensions, preview image
 *   3. Online quote → itemised cost per quantity
 *   4. Create order (called by ordermanager.js in S16)
 *
 * If API credentials are not configured or API calls fail, falls back
 * to the rate card in data/fab_rates/jlcpcb.json.
 *
 * All requests must be signed (jlcpcb-signer.js).
 * Every response's J-Trace-ID header is logged for debugging.
 */

const axios  = require('axios');
const fs     = require('fs');
const path   = require('path');
const FormData = require('form-data');
const { signRequest } = require('./jlcpcb-signer');
const { getQuote }    = require('./rate-card-engine');

const BASE_URL  = 'https://open.jlcpcb.com';
const RATE_CARD = require(path.join(__dirname, '..', '..', 'data', 'fab_rates', 'jlcpcb.json'));

// ─── Config ──────────────────────────────────────────────────────────────────

function getCredentials() {
  const appId     = process.env.JLCPCB_APP_ID;
  const accessKey = process.env.JLCPCB_ACCESS_KEY;
  const secretKey = process.env.JLCPCB_SECRET_KEY;

  if (!appId || appId === 'your_app_id' ||
      !accessKey || accessKey === 'your_access_key' ||
      !secretKey || secretKey === 'your_secret_key') {
    return null;
  }
  return { appId, accessKey, secretKey };
}

// Singleton signed client
let _client = null;
function getClient() {
  if (!_client) {
    const creds = getCredentials();
    if (!creds) return null;

    _client = axios.create({ baseURL: BASE_URL, timeout: 30_000 });
    _client.interceptors.request.use(config => signRequest(config, creds));
    _client.interceptors.response.use(res => {
      // Log J-Trace-ID on every response
      const traceId = res.headers['j-trace-id'] || res.headers['J-Trace-ID'];
      if (traceId) console.log(`[jlcpcb] J-Trace-ID: ${traceId}`);
      return res;
    });
  }
  return _client;
}

function isSuccessful(res) {
  return res.status === 200 && res.data?.code === 0;
}

// ─── API methods ─────────────────────────────────────────────────────────────

/**
 * Upload Gerber ZIP to JLCPCB. Returns gerber_file_id.
 */
async function uploadGerbers(gerberZipPath) {
  const client = getClient();
  if (!client) throw new Error('JLCPCB API not configured');

  const form = new FormData();
  form.append('file', fs.createReadStream(gerberZipPath));

  const res = await client.post('/api/pcb/gerber/upload', form, {
    headers: { ...form.getHeaders() },
    maxContentLength: 50 * 1024 * 1024,
  });

  if (!isSuccessful(res)) {
    throw new Error(`JLCPCB Gerber upload failed: ${res.data?.message || res.statusText}`);
  }

  return res.data.data?.gerberFileId || res.data.data?.gerber_file_id;
}

/**
 * Get pre-review info for uploaded Gerbers.
 * Returns { width_mm, height_mm, layers, preview_url }.
 */
async function getPreReview(gerberFileId) {
  const client = getClient();
  if (!client) throw new Error('JLCPCB API not configured');

  const res = await client.post('/api/pcb/gerber/pre-review', {
    gerberFileId,
    language: 'en',
  });

  if (!isSuccessful(res)) {
    throw new Error(`JLCPCB pre-review failed: ${res.data?.message || res.statusText}`);
  }

  const d = res.data.data || {};
  return {
    width_mm:    d.width || d.widthMm,
    height_mm:   d.height || d.heightMm,
    layers:      d.layerCount || d.layers,
    preview_url: d.previewImage || d.previewUrl || null,
  };
}

/**
 * Get live online quote from JLCPCB.
 *
 * boardSpec: { dimensions_mm, layers, surface_finish, copper_weight_oz }
 * gerberFileId: from uploadGerbers()
 * quantities: [5, 10, 25, 50, 100]
 *
 * Returns: { quotes: { [qty]: price_usd }, lead_days, gerber_file_id }
 */
async function getLiveQuote(boardSpec, gerberFileId, quantities = [5, 10, 25, 50, 100]) {
  const client = getClient();
  if (!client) throw new Error('JLCPCB API not configured');

  const [w, h] = boardSpec.dimensions_mm || [100, 80];
  const quotes = {};

  // Request quotes for each quantity
  for (const qty of quantities) {
    try {
      const res = await client.post('/api/pcb/quote', {
        gerberFileId,
        quantity:       qty,
        layers:         boardSpec.layers || 2,
        pcbWidth:       w,
        pcbHeight:      h,
        surfaceFinish:  mapFinish(boardSpec.surface_finish),
        copperWeight:   boardSpec.copper_weight_oz || 1,
        thickness:      boardSpec.thickness_mm || 1.6,
        material:       'FR4',
      });

      if (isSuccessful(res)) {
        const d = res.data.data || {};
        quotes[qty] = d.totalPrice || d.total_price || d.unitPrice * qty;
      }
    } catch (err) {
      console.warn(`[jlcpcb] Quote for qty ${qty} failed: ${err.message}`);
    }
  }

  return {
    quotes,
    lead_days: 5,
    gerber_file_id: gerberFileId,
  };
}

/**
 * Create a manufacturing order on JLCPCB.
 * Called by ordermanager.js (Session 16).
 */
async function createOrder({ gerberFileId, boardSpec, quantity, shippingAddress }) {
  const client = getClient();
  if (!client) throw new Error('JLCPCB API not configured');

  const [w, h] = boardSpec.dimensions_mm || [100, 80];

  const res = await client.post('/api/pcb/order/create', {
    gerberFileId,
    quantity,
    layers:         boardSpec.layers || 2,
    pcbWidth:       w,
    pcbHeight:      h,
    surfaceFinish:  mapFinish(boardSpec.surface_finish),
    copperWeight:   boardSpec.copper_weight_oz || 1,
    thickness:      boardSpec.thickness_mm || 1.6,
    material:       'FR4',
    shippingAddress,
  });

  if (!isSuccessful(res)) {
    throw new Error(`JLCPCB order creation failed: ${res.data?.message || res.statusText}`);
  }

  const d = res.data.data || {};
  return {
    order_id:     d.orderId || d.order_id,
    batch_number: d.batchNumber || d.batch_number,
  };
}

// ─── Surface finish mapping ──────────────────────────────────────────────────

function mapFinish(finish) {
  const MAP = {
    hasl_leadfree:    1,
    hasl_leaded:      2,
    enig:             3,
    osp:              4,
    immersion_silver: 5,
    immersion_tin:    6,
  };
  return MAP[finish] || 1;
}

// ─── Main quote function (live API with rate card fallback) ──────────────────

/**
 * quote(boardSpec, gerberZipPath)
 *
 * Tries live API first. If API is not configured or fails, falls back
 * to rate card. Returns same shape as other adapters.
 */
async function quote(boardSpec, gerberZipPath) {
  const creds = getCredentials();

  // Try live API if credentials are configured and Gerbers are available
  if (creds && gerberZipPath && fs.existsSync(gerberZipPath)) {
    try {
      console.log('[jlcpcb] Attempting live API quote...');
      const gerberFileId = await uploadGerbers(gerberZipPath);
      const preReview    = await getPreReview(gerberFileId);

      // Cross-check parsed dimensions vs board spec
      const [specW, specH] = boardSpec.dimensions_mm || [100, 80];
      if (preReview.width_mm && preReview.height_mm) {
        const wDiff = Math.abs(preReview.width_mm - specW);
        const hDiff = Math.abs(preReview.height_mm - specH);
        if (wDiff > 5 || hDiff > 5) {
          console.warn(`[jlcpcb] Dimension mismatch: spec ${specW}x${specH}mm vs parsed ${preReview.width_mm}x${preReview.height_mm}mm`);
        }
      }

      const liveResult = await getLiveQuote(boardSpec, gerberFileId);

      if (Object.keys(liveResult.quotes).length > 0) {
        return {
          fab:                'JLCPCB',
          method:             'api_live',
          currency:           'USD',
          quotes:             liveResult.quotes,
          lead_days:          liveResult.lead_days,
          assembly_available: true,
          note:               '',
          url:                'https://jlcpcb.com/quote',
          gerber_file_id:     liveResult.gerber_file_id,
        };
      }
    } catch (err) {
      console.warn(`[jlcpcb] Live API failed, falling back to rate card: ${err.message}`);
    }
  }

  // Rate card fallback
  console.log('[jlcpcb] Using rate card fallback');
  const rateCardResult = getQuote(RATE_CARD, boardSpec);
  rateCardResult.method = 'rate_card_fallback';
  return rateCardResult;
}

module.exports = {
  quote,
  uploadGerbers,
  getPreReview,
  getLiveQuote,
  createOrder,
  RATE_CARD,
};
