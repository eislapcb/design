'use strict';

require('dotenv').config();

const express = require('express');
const cors    = require('cors');
const fs      = require('fs');
const path    = require('path');
const { resolve }      = require('./resolver');
const { parseIntent }  = require('./nlparser');
const { register, login, logout, changePassword, requireAuth } = require('./accounts');

const app  = express();
const PORT = process.env.PORT || 3001; // ops hub runs on 3000

// ─── Middleware ───────────────────────────────────────────────────────────────

app.use(cors());
app.use(express.json());

// ─── Routes ───────────────────────────────────────────────────────────────────

/**
 * GET /api/health
 */
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', version: '2.0.0', timestamp: new Date().toISOString() });
});

/**
 * GET /api/capabilities
 * Returns the full capability taxonomy.
 */
app.get('/api/capabilities', (req, res) => {
  try {
    const caps = JSON.parse(
      fs.readFileSync(path.join(__dirname, '..', 'data', 'capabilities.json'), 'utf8')
    );
    res.json(caps);
  } catch (err) {
    res.status(500).json({ error: 'Failed to load capabilities' });
  }
});

/**
 * GET /api/components
 * Returns the full component database (summary fields only).
 */
app.get('/api/components', (req, res) => {
  try {
    const all = JSON.parse(
      fs.readFileSync(path.join(__dirname, '..', 'data', 'components.json'), 'utf8')
    );
    // Return summary — omit bulky fields like layout_notes
    const summary = Object.fromEntries(
      Object.entries(all).map(([id, c]) => [id, {
        id:                  c.id,
        display_name:        c.display_name,
        category:            c.category,
        subcategory:         c.subcategory,
        capabilities:        c.capabilities,
        cost_gbp_unit:       c.cost_gbp_unit,
        power_consumption_ma: c.power_consumption_ma,
        supply_voltage:      c.supply_voltage,
        tier:                c.tier,
        mpn:                 c.mpn,
      }])
    );
    res.json(summary);
  } catch (err) {
    res.status(500).json({ error: 'Failed to load components' });
  }
});

/**
 * GET /api/components/:id
 * Returns full detail for a single component.
 */
app.get('/api/components/:id', (req, res) => {
  try {
    const all = JSON.parse(
      fs.readFileSync(path.join(__dirname, '..', 'data', 'components.json'), 'utf8')
    );
    const comp = all[req.params.id];
    if (!comp) return res.status(404).json({ error: `Component '${req.params.id}' not found` });
    res.json(comp);
  } catch (err) {
    res.status(500).json({ error: 'Failed to load component' });
  }
});

/**
 * POST /api/parse-intent
 * Converts a plain-English project description into capability selections.
 *
 * Body: { "description": "I want to build a plant watering monitor..." }
 * Response: { success, result: { capabilities, suggested_board, confidence_notes } }
 *   or on failure: { success: false, error: "..." }
 */
app.post('/api/parse-intent', async (req, res) => {
  const { description } = req.body;

  if (!description || typeof description !== 'string' || !description.trim()) {
    return res.status(400).json({ success: false, error: '`description` must be a non-empty string' });
  }

  try {
    const parsed = await parseIntent(description.trim());
    // Always 200 — caller checks parsed.success; failures are handled gracefully in UI
    res.json(parsed);
  } catch (err) {
    console.error('[parse-intent] unexpected error:', err);
    res.status(500).json({ success: false, error: 'Parser error', detail: err.message });
  }
});

/**
 * POST /api/resolve
 * Core resolver endpoint — converts capability selections into a component list.
 *
 * Body: {
 *   capabilities: string[],
 *   board: { layers?: number, dimensions_mm?: [number, number], power_source?: string },
 *   repeat_customer?: boolean
 * }
 */
app.post('/api/resolve', (req, res) => {
  const { capabilities, board, repeat_customer } = req.body;

  if (!Array.isArray(capabilities)) {
    return res.status(400).json({ error: '`capabilities` must be an array of capability IDs' });
  }

  try {
    const result = resolve({ capabilities, board: board || {}, repeat_customer: !!repeat_customer });
    res.json(result);
  } catch (err) {
    console.error('[resolve] error:', err);
    res.status(500).json({ error: 'Resolver failed', detail: err.message });
  }
});

// ─── Auth routes ─────────────────────────────────────────────────────────────

/**
 * POST /api/auth/register
 * Body: { name, email, password }
 */
app.post('/api/auth/register', async (req, res) => {
  const { name, email, password } = req.body || {};
  if (!name || !email || !password) {
    return res.status(400).json({ success: false, error: 'name, email and password are required' });
  }
  try {
    const result = await register({ name, email, password });
    res.status(result.success ? 201 : 400).json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

/**
 * POST /api/auth/login
 * Body: { email, password }
 * Returns: { success, session: { access_token, refresh_token }, profile }
 */
app.post('/api/auth/login', async (req, res) => {
  const { email, password } = req.body || {};
  if (!email || !password) {
    return res.status(400).json({ success: false, error: 'email and password are required' });
  }
  try {
    const result = await login({ email, password });
    res.status(result.success ? 200 : 401).json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

/**
 * POST /api/auth/logout
 * Requires: Authorization: Bearer <access_token>
 */
app.post('/api/auth/logout', async (req, res) => {
  const token = req.headers.authorization?.slice(7);
  if (!token) return res.status(401).json({ success: false, error: 'No token provided' });
  try {
    const result = await logout(token);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

/**
 * POST /api/auth/change-password
 * Requires auth. Body: { newPassword }
 */
app.post('/api/auth/change-password', requireAuth, async (req, res) => {
  const { newPassword } = req.body || {};
  if (!newPassword) return res.status(400).json({ success: false, error: 'newPassword required' });
  const token = req.headers.authorization.slice(7);
  try {
    const result = await changePassword(token, newPassword);
    res.status(result.success ? 200 : 400).json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

/**
 * GET /api/auth/me
 * Returns the authenticated customer's profile.
 */
app.get('/api/auth/me', requireAuth, (req, res) => {
  res.json({ success: true, user: req.user, profile: req.profile });
});

// ─── 404 handler ─────────────────────────────────────────────────────────────

app.use((req, res) => {
  res.status(404).json({ error: `No route for ${req.method} ${req.path}` });
});

// ─── Start ────────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`Eisla API running on http://localhost:${PORT}`);
  console.log(`  GET  /api/health`);
  console.log(`  GET  /api/capabilities`);
  console.log(`  GET  /api/components`);
  console.log(`  GET  /api/components/:id`);
  console.log(`  POST /api/parse-intent`);
  console.log(`  POST /api/resolve`);
  console.log(`  POST /api/auth/register`);
  console.log(`  POST /api/auth/login`);
  console.log(`  POST /api/auth/logout`);
  console.log(`  POST /api/auth/change-password`);
  console.log(`  GET  /api/auth/me`);
});

module.exports = app;
