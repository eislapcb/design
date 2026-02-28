'use strict';

require('dotenv').config();

const express = require('express');
const cors    = require('cors');
const fs      = require('fs');
const path    = require('path');
const { resolve }      = require('./resolver');
const { parseIntent }  = require('./nlparser');
const { register, login, logout, changePassword, requireAuth } = require('./accounts');
const { createDesignCheckout, createManufacturingCheckout, createCreditCheckout, handleWebhook } = require('./stripe');
const { enqueue }                = require('./queue');
const { readJobFile, jobDir }    = require('./worker');
const { getOrdersByDesign, updateOrderStatus } = require('./ordermanager');

const app  = express();
const PORT = process.env.PORT || 3001; // ops hub runs on 3000

// ─── Stripe webhook (raw body — MUST come before express.json()) ──────────────
// Stripe needs the raw request body to verify the signature.

app.post('/api/webhook', express.raw({ type: 'application/json' }), handleWebhook);

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

// ─── Stripe routes ───────────────────────────────────────────────────────────

/**
 * POST /api/checkout
 * Creates a Stripe Checkout session for the design fee.
 * Body: { tier, repeat_customer?, promo?, service_level?, boardConfig, capabilities, userEmail? }
 */
app.post('/api/checkout', requireAuth, async (req, res) => {
  const { tier, repeat_customer, promo, service_level, boardConfig, capabilities } = req.body;
  if (!tier || !boardConfig || !capabilities) {
    return res.status(400).json({ error: 'tier, boardConfig and capabilities are required' });
  }
  try {
    const result = await createDesignCheckout({
      tier:            parseInt(tier, 10),
      repeat_customer: !!repeat_customer,
      promo:           !!promo,
      service_level:   service_level || 'standard',
      boardConfig,
      capabilities,
      userId:          req.user?.id    || null,
      userEmail:       req.user?.email || null,
    });
    res.json({ success: true, url: result.url, sessionId: result.sessionId });
  } catch (err) {
    console.error('[checkout] error:', err.message);
    res.status(500).json({ success: false, error: err.message });
  }
});

/**
 * POST /api/manufacturing-checkout
 * Creates a Stripe Checkout session for a manufacturing order.
 * Body: { jobId, fab, quantity, rawPriceGbp, jobType?, quoteGeneratedAt? }
 */
app.post('/api/manufacturing-checkout', requireAuth, async (req, res) => {
  const { jobId, fab, quantity, rawPriceGbp, jobType, quoteGeneratedAt } = req.body;
  if (!jobId || !fab || !quantity || rawPriceGbp == null) {
    return res.status(400).json({ error: 'jobId, fab, quantity and rawPriceGbp are required' });
  }
  try {
    const result = await createManufacturingCheckout({
      jobId,
      fab,
      quantity:        parseInt(quantity, 10),
      rawPriceGbp:     parseFloat(rawPriceGbp),
      jobType:         jobType || 'new',
      quoteGeneratedAt,
      userId:          req.user?.id    || null,
      userEmail:       req.user?.email || null,
    });
    res.json({ success: true, url: result.url, sessionId: result.sessionId });
  } catch (err) {
    console.error('[manufacturing-checkout] error:', err.message);
    const isExpired = err.message.includes('expired');
    res.status(isExpired ? 410 : 500).json({ success: false, error: err.message });
  }
});

/**
 * POST /api/checkout/credits
 * Creates a Stripe Checkout session for a credit pack purchase.
 * Body: { packSize: 1 | 3 | 5 }
 */
app.post('/api/checkout/credits', requireAuth, async (req, res) => {
  const { packSize } = req.body;
  if (!packSize) return res.status(400).json({ error: 'packSize required (1, 3, or 5)' });
  try {
    const result = await createCreditCheckout({
      packSize:  parseInt(packSize, 10),
      userId:    req.user?.id    || null,
      userEmail: req.user?.email || null,
    });
    res.json({ success: true, url: result.url, sessionId: result.sessionId });
  } catch (err) {
    console.error('[checkout/credits] error:', err.message);
    res.status(400).json({ success: false, error: err.message });
  }
});

// ─── Job routes ───────────────────────────────────────────────────────────────
//
// All routes require the caller to own the design (userId match in Supabase).
// Supabase admin client is created inline to avoid circular imports.

async function getOwnedDesign(designId, userId) {
  const { createClient } = require('@supabase/supabase-js');
  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
  );
  const { data, error } = await admin
    .from('designs')
    .select('*')
    .eq('id', designId)
    .single();
  if (error || !data) throw Object.assign(new Error('Design not found'), { status: 404 });
  if (userId && data.user_id !== userId) throw Object.assign(new Error('Forbidden'), { status: 403 });
  return data;
}

/**
 * GET /api/jobs/:id/status
 * Returns current pipeline status for a design.
 */
app.get('/api/jobs/:id/status', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);
    res.json({
      success:   true,
      designId:  design.id,
      status:    design.status,
      updatedAt: design.updated_at,
    });
  } catch (err) {
    res.status(err.status || 500).json({ success: false, error: err.message });
  }
});

/**
 * GET /api/jobs/:id/review-summary
 * Returns placement layout + validation warnings for the customer review screen.
 * Only available when status is awaiting_placement_approval.
 */
app.get('/api/jobs/:id/review-summary', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);

    if (!['awaiting_placement_approval', 'placing', 'failed'].includes(design.status)) {
      return res.status(409).json({
        success: false,
        error:   `Cannot review — design status is '${design.status}'`,
      });
    }

    const placement = readJobFile(design.id, 'placement.json');
    const warnings  = readJobFile(design.id, 'validation_warnings.json');

    if (!placement) {
      return res.status(404).json({ success: false, error: 'Placement data not ready' });
    }

    res.json({
      success:    true,
      designId:   design.id,
      status:     design.status,
      placement,
      warnings:   warnings || { warnings: [], auto_resolved: [] },
      svgUrl:     `/api/jobs/${design.id}/preview.svg`,
    });
  } catch (err) {
    res.status(err.status || 500).json({ success: false, error: err.message });
  }
});

/**
 * GET /api/jobs/:id/preview.svg
 * Streams the placement preview SVG file.
 */
app.get('/api/jobs/:id/preview.svg', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);
    const svgPath = path.join(jobDir(design.id), 'placement_preview.svg');
    if (!fs.existsSync(svgPath)) {
      return res.status(404).json({ error: 'Preview SVG not ready' });
    }
    res.setHeader('Content-Type', 'image/svg+xml');
    fs.createReadStream(svgPath).pipe(res);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

/**
 * POST /api/jobs/:id/approve-placement
 * Customer approves the placement. Advances to routing.
 */
app.post('/api/jobs/:id/approve-placement', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);

    if (design.status !== 'awaiting_placement_approval') {
      return res.status(409).json({
        success: false,
        error:   `Cannot approve — design status is '${design.status}'`,
      });
    }

    await enqueue('approve-placement', { designId: design.id });
    res.json({ success: true, message: 'Placement approved — routing queued' });
  } catch (err) {
    res.status(err.status || 500).json({ success: false, error: err.message });
  }
});

/**
 * POST /api/jobs/:id/adjust-placement
 * Customer submits position/rotation overrides. Re-renders SVG.
 * Body: { adjustments: { U1: { x_mm, y_mm, rotation_deg }, ... } }
 */
app.post('/api/jobs/:id/adjust-placement', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);

    if (design.status !== 'awaiting_placement_approval') {
      return res.status(409).json({
        success: false,
        error:   `Cannot adjust — design status is '${design.status}'`,
      });
    }

    const { adjustments } = req.body;
    if (!adjustments || typeof adjustments !== 'object') {
      return res.status(400).json({ success: false, error: 'adjustments object required' });
    }

    await enqueue('adjust-placement', { designId: design.id, adjustments });
    res.json({ success: true, message: 'Adjustments queued — preview will update shortly' });
  } catch (err) {
    res.status(err.status || 500).json({ success: false, error: err.message });
  }
});

/**
 * GET /api/jobs/:id/quotes
 * Returns manufacturing quotes (customer-facing prices only — raw fab prices stripped).
 * Only available when status is 'quoting' or 'files_ready'.
 */
app.get('/api/jobs/:id/quotes', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);

    if (!['quoting', 'files_ready', 'complete'].includes(design.status)) {
      return res.status(409).json({
        success: false,
        error:   `Quotes not available — design status is '${design.status}'`,
      });
    }

    const fabQuotes = readJobFile(design.id, 'fab_quotes.json');
    if (!fabQuotes) {
      return res.json({
        success:  true,
        designId: design.id,
        quotes:   [],
        note:     'Quoting in progress — check back shortly',
      });
    }

    // Strip raw_gbp from each quote — never expose raw fab prices
    const safeQuotes = (fabQuotes.quotes || []).map(q => ({
      fab:                q.fab,
      method:             q.method,
      assembly_available: q.assembly_available,
      note:               q.note,
      url:                q.url,
      quotes: Object.fromEntries(
        Object.entries(q.quotes || {}).map(([qty, v]) => [
          qty,
          { customer_gbp: v.customer_gbp, lead_days: v.lead_days },
        ])
      ),
    }));

    res.json({
      success:      true,
      designId:     design.id,
      generated_at: fabQuotes.generated_at,
      quotes:       safeQuotes,
    });
  } catch (err) {
    res.status(err.status || 500).json({ success: false, error: err.message });
  }
});

/**
 * GET /api/jobs/:id/download
 * Returns the output ZIP (Gerbers, BOM, pick-and-place).
 * Only available when status is 'files_ready' or 'complete'.
 */
app.get('/api/jobs/:id/download', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);

    if (!['files_ready', 'complete'].includes(design.status)) {
      return res.status(409).json({
        success: false,
        error:   `Files not ready — design status is '${design.status}'`,
      });
    }

    const zipPath = path.join(jobDir(design.id), 'output.zip');
    if (!fs.existsSync(zipPath)) {
      return res.status(404).json({ success: false, error: 'Output ZIP not found' });
    }

    res.setHeader('Content-Type', 'application/zip');
    res.setHeader('Content-Disposition', `attachment; filename="eisla-${design.id}.zip"`);
    fs.createReadStream(zipPath).pipe(res);
  } catch (err) {
    res.status(err.status || 500).json({ success: false, error: err.message });
  }
});

// ─── Internal routes (ops hub → design system) ──────────────────────────────
//
// These endpoints are called by the ops hub, not by customers.
// Auth: service-role key in x-service-key header.

function requireServiceKey(req, res, next) {
  const key = req.headers['x-service-key'];
  if (!key || key !== process.env.SUPABASE_SERVICE_ROLE_KEY) {
    return res.status(401).json({ error: 'Invalid service key' });
  }
  next();
}

/**
 * POST /api/internal/approve-review
 * Ops hub engineer approves a T2/T3 design. Advances to customer placement approval.
 * Body: { designId }
 */
app.post('/api/internal/approve-review', requireServiceKey, async (req, res) => {
  try {
    const { designId } = req.body;
    if (!designId) return res.status(400).json({ error: 'designId required' });

    const { createClient } = require('@supabase/supabase-js');
    const admin = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL,
      process.env.SUPABASE_SERVICE_ROLE_KEY
    );
    const { data: design, error } = await admin
      .from('designs')
      .select('id, status')
      .eq('id', designId)
      .single();

    if (error || !design) {
      return res.status(404).json({ error: 'Design not found' });
    }
    if (design.status !== 'awaiting_engineer_review') {
      return res.status(409).json({
        error: `Cannot approve review — status is '${design.status}'`,
      });
    }

    await enqueue('engineer-reviewed', { designId });
    res.json({ success: true, message: 'Engineer review approved — advancing to customer approval' });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── Manufacturing order routes ──────────────────────────────────────────────

/**
 * GET /api/jobs/:id/orders
 * Returns manufacturing orders for a design (customer-facing — raw prices stripped).
 */
app.get('/api/jobs/:id/orders', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);
    const orders = await getOrdersByDesign(design.id);

    // Strip internal fields
    const safeOrders = orders.map(o => ({
      id:               o.id,
      fab:              o.fab,
      quantity:         o.quantity,
      status:           o.status,
      fab_order_ref:    o.fab_order_ref,
      customer_price_gbp: o.customer_price_gbp,
      created_at:       o.created_at,
    }));

    res.json({ success: true, orders: safeOrders });
  } catch (err) {
    res.status(err.status || 500).json({ success: false, error: err.message });
  }
});

/**
 * POST /api/jobs/:id/reorder
 * Re-place a manufacturing order for a completed design.
 * Generates fresh quotes and creates a new Stripe checkout session.
 * Body: { fab, quantity }
 */
app.post('/api/jobs/:id/reorder', requireAuth, async (req, res) => {
  try {
    const design = await getOwnedDesign(req.params.id, req.user?.id);

    if (!['files_ready', 'complete'].includes(design.status)) {
      return res.status(409).json({
        success: false,
        error: `Cannot reorder — design status is '${design.status}'`,
      });
    }

    const { fab, quantity } = req.body;
    if (!fab || !quantity) {
      return res.status(400).json({ error: 'fab and quantity are required' });
    }

    // Read fresh quotes
    const fabQuotes = readJobFile(design.id, 'fab_quotes.json');
    if (!fabQuotes) {
      return res.status(409).json({ error: 'No quotes available for this design' });
    }

    const fabQuote = (fabQuotes.quotes || []).find(q => q.fab === fab);
    const qty = parseInt(quantity, 10);
    const qtyQuote = fabQuote?.quotes?.[qty];

    if (!qtyQuote) {
      return res.status(400).json({ error: `No quote for ${fab} × ${qty}` });
    }

    // Create manufacturing checkout with reorder pricing
    const result = await createManufacturingCheckout({
      jobId:            design.id,
      fab,
      quantity:         qty,
      rawPriceGbp:      qtyQuote.raw_gbp,
      jobType:          'reorder',
      quoteGeneratedAt: fabQuotes.generated_at,
      userId:           req.user?.id || null,
      userEmail:        req.user?.email || null,
    });

    res.json({ success: true, url: result.url, sessionId: result.sessionId });
  } catch (err) {
    const isExpired = err.message?.includes('expired');
    res.status(isExpired ? 410 : 500).json({ success: false, error: err.message });
  }
});

/**
 * POST /api/internal/update-order
 * Ops hub updates order tracking info (e.g. shipped, tracking number).
 * Body: { orderId, status, trackingRef?, fabOrderRef? }
 */
app.post('/api/internal/update-order', requireServiceKey, async (req, res) => {
  try {
    const { orderId, status, trackingRef, fabOrderRef } = req.body;
    if (!orderId || !status) {
      return res.status(400).json({ error: 'orderId and status are required' });
    }

    const fields = {};
    if (trackingRef)  fields.tracking_ref  = trackingRef;
    if (fabOrderRef)  fields.fab_order_ref = fabOrderRef;

    await updateOrderStatus(orderId, status, fields);
    res.json({ success: true, message: `Order ${orderId} → ${status}` });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
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
  console.log(`  POST /api/checkout`);
  console.log(`  POST /api/manufacturing-checkout`);
  console.log(`  POST /api/checkout/credits`);
  console.log(`  POST /api/webhook`);
  console.log(`  GET  /api/jobs/:id/status`);
  console.log(`  GET  /api/jobs/:id/review-summary`);
  console.log(`  GET  /api/jobs/:id/preview.svg`);
  console.log(`  POST /api/jobs/:id/approve-placement`);
  console.log(`  POST /api/jobs/:id/adjust-placement`);
  console.log(`  GET  /api/jobs/:id/quotes`);
  console.log(`  GET  /api/jobs/:id/download`);
  console.log(`  GET  /api/jobs/:id/orders`);
  console.log(`  POST /api/jobs/:id/reorder`);
  console.log(`  POST /api/internal/approve-review`);
  console.log(`  POST /api/internal/update-order`);
});

module.exports = app;
