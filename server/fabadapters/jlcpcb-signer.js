'use strict';

/**
 * Eisla — JLCPCB Request Signer (server/fabadapters/jlcpcb-signer.js)
 *
 * Session 15. Implements JLCPCB API request signing for Node.js.
 *
 * The official JLCPCB SDK is Java-only. This module replicates the signing
 * algorithm based on the SDK's core package. The signature is computed as:
 *
 *   1. Canonical string = HTTP method + \n + path + \n + sorted query params + \n + timestamp
 *   2. Signature = HMAC-SHA256(secretKey, canonical string)
 *   3. Auth header = "JLC appId={appId}, accessKey={accessKey}, timestamp={ts}, signature={sig}"
 *
 * NOTE: The exact signing algorithm must be verified against the Java SDK source.
 * If requests return 401, the signing logic here needs adjustment. The structure
 * is correct but field ordering / canonicalisation may differ.
 */

const crypto = require('crypto');

/**
 * Sign an axios request config for JLCPCB API.
 *
 * @param {object} config - axios request config (url, method, data, params)
 * @param {object} creds  - { appId, accessKey, secretKey }
 * @returns {object}      - modified config with Authorization header
 */
function signRequest(config, { appId, accessKey, secretKey }) {
  const timestamp = Date.now().toString();
  const method = (config.method || 'POST').toUpperCase();

  // Extract path from URL (strip base URL if present)
  let path = config.url || '/';
  try {
    const u = new URL(path, 'https://open.jlcpcb.com');
    path = u.pathname;
  } catch {
    // already a path
  }

  // Sort query params alphabetically
  const params = config.params || {};
  const sortedParams = Object.keys(params)
    .sort()
    .map(k => `${k}=${params[k]}`)
    .join('&');

  // Build canonical string
  const canonical = [method, path, sortedParams, timestamp].join('\n');

  // HMAC-SHA256 signature
  const signature = crypto
    .createHmac('sha256', secretKey)
    .update(canonical)
    .digest('hex');

  // Set auth header
  config.headers = config.headers || {};
  config.headers['Authorization'] =
    `JLC appId=${appId}, accessKey=${accessKey}, timestamp=${timestamp}, signature=${signature}`;
  config.headers['Content-Type'] = config.headers['Content-Type'] || 'application/json';

  return config;
}

module.exports = { signRequest };
