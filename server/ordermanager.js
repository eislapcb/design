'use strict';

/**
 * Eisla — Manufacturing Order Manager (server/ordermanager.js)
 *
 * Session 16. Handles placing manufacturing orders with fabs after
 * the customer pays via the Stripe manufacturing checkout.
 *
 * Flow:
 *   1. Stripe webhook calls placeOrder() with payment metadata + shipping
 *   2. Create an order row in Supabase `manufacturing_orders` table
 *   3. Dispatch to the correct fab:
 *      - JLCPCB:       Live API (jlcpcb.createOrder) using stored gerber_file_id
 *      - PCBTrain:      Manual fulfilment — operator notification email
 *      - PCBWay:        Manual fulfilment — operator notification email
 *      - Eurocircuits:  Manual fulfilment — operator notification email
 *   4. Update order status and fab references
 *
 * Order statuses: pending → placed → shipped → delivered | failed
 */

const fs   = require('fs');
const path = require('path');
const { v4: uuidv4 } = require('uuid');
const { createClient } = require('@supabase/supabase-js');
const notifier = require('./notifier');

// ─── Helpers ─────────────────────────────────────────────────────────────────

function supaAdmin() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
  );
}

const JOBS_DIR = path.resolve(process.env.JOBS_DIR || './jobs');

function readJobFile(designId, filename) {
  const p = path.join(JOBS_DIR, designId, filename);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

// ─── Main: place order ───────────────────────────────────────────────────────

/**
 * placeOrder(options)
 *
 * Called from stripe.js handleManufacturingPaid webhook.
 *
 * options: {
 *   designId,
 *   fab,               // 'JLCPCB' | 'PCBTrain' | 'PCBWay' | 'Eurocircuits'
 *   quantity,           // integer
 *   customerPriceGbp,   // what the customer paid (incl. margin)
 *   rawPriceGbp,        // internal raw fab cost in GBP (from fab_quotes.json)
 *   stripeSessionId,    // Stripe session ID for idempotency
 *   userId,             // customer UUID or null
 *   shipping,           // Stripe shipping_details object
 * }
 *
 * Returns: { orderId, status, fabOrderRef? }
 */
async function placeOrder({
  designId,
  fab,
  quantity,
  customerPriceGbp,
  rawPriceGbp,
  stripeSessionId,
  userId = null,
  shipping = null,
}) {
  const admin = supaAdmin();
  const orderId = uuidv4();

  // Idempotency: check if order already exists for this Stripe session
  const { data: existing } = await admin
    .from('manufacturing_orders')
    .select('id')
    .eq('stripe_session_id', stripeSessionId)
    .maybeSingle();

  if (existing) {
    console.log(`[ordermanager] Duplicate — order already exists for session ${stripeSessionId}`);
    return { orderId: existing.id, status: 'already_exists' };
  }

  // Create order record
  const { error: insertError } = await admin
    .from('manufacturing_orders')
    .insert({
      id:                 orderId,
      design_id:          designId,
      customer_id:        userId || null,
      fab,
      quantity,
      customer_price_gbp: customerPriceGbp,
      raw_fab_price_gbp:  rawPriceGbp || null,
      status:             'pending',
      stripe_session_id:  stripeSessionId,
      shipping_address:   shipping ? formatShipping(shipping) : null,
    });

  if (insertError) {
    throw new Error(`Failed to create order record: ${insertError.message}`);
  }

  console.log(`[ordermanager] Order ${orderId} created — ${fab} × ${quantity}`);

  // Dispatch to fab
  let fabOrderRef = null;
  let batchNumber = null;

  try {
    switch (fab) {
      case 'JLCPCB':
        ({ fabOrderRef, batchNumber } = await placeJlcpcbOrder(designId, quantity, shipping));
        break;
      case 'PCBTrain':
      case 'PCBWay':
      case 'Eurocircuits':
        await notifyManualFulfilment(orderId, designId, fab, quantity, shipping);
        break;
      default:
        console.warn(`[ordermanager] Unknown fab: ${fab} — flagging for manual fulfilment`);
        await notifyManualFulfilment(orderId, designId, fab, quantity, shipping);
    }

    // Update order with fab references
    const updates = { status: fabOrderRef ? 'placed' : 'pending_manual' };
    if (fabOrderRef) updates.fab_order_ref = fabOrderRef;
    if (batchNumber) updates.batch_number = batchNumber;

    await admin
      .from('manufacturing_orders')
      .update(updates)
      .eq('id', orderId);

    console.log(`[ordermanager] Order ${orderId} → ${updates.status}${fabOrderRef ? ` (ref: ${fabOrderRef})` : ''}`);
    return { orderId, status: updates.status, fabOrderRef };

  } catch (err) {
    console.error(`[ordermanager] Fab dispatch failed for ${orderId}: ${err.message}`);

    await admin
      .from('manufacturing_orders')
      .update({ status: 'failed', error_message: err.message })
      .eq('id', orderId);

    // Fall back to manual fulfilment notification
    await notifyManualFulfilment(orderId, designId, fab, quantity, shipping);

    return { orderId, status: 'failed', error: err.message };
  }
}

// ─── JLCPCB live order ───────────────────────────────────────────────────────

async function placeJlcpcbOrder(designId, quantity, shipping) {
  const jlcpcb = require('./fabadapters/jlcpcb');
  const fabQuotes = readJobFile(designId, 'fab_quotes.json');
  const boardJson = readJobFile(designId, 'board.json') || {};

  // Find stored gerber_file_id from quoting stage
  const jlcpcbQuote = (fabQuotes?.quotes || []).find(q => q.fab === 'JLCPCB');
  const gerberFileId = jlcpcbQuote?.gerber_file_id;

  if (!gerberFileId) {
    throw new Error('No JLCPCB gerber_file_id found — cannot place automated order');
  }

  const shippingAddress = shipping ? {
    name:    shipping.name,
    line1:   shipping.address?.line1,
    line2:   shipping.address?.line2,
    city:    shipping.address?.city,
    state:   shipping.address?.state,
    postal:  shipping.address?.postal_code,
    country: shipping.address?.country,
  } : null;

  const result = await jlcpcb.createOrder({
    gerberFileId,
    boardSpec: boardJson,
    quantity,
    shippingAddress,
  });

  return {
    fabOrderRef: result.order_id,
    batchNumber: result.batch_number,
  };
}

// ─── Manual fulfilment notification ──────────────────────────────────────────

async function notifyManualFulfilment(orderId, designId, fab, quantity, shipping) {
  const operatorEmail = process.env.OPERATOR_EMAIL;
  if (!operatorEmail) {
    console.warn('[ordermanager] OPERATOR_EMAIL not configured — cannot send manual fulfilment notification');
    return;
  }

  const addr = shipping ? formatShipping(shipping) : 'No address provided';
  const boardJson = readJobFile(designId, 'board.json') || {};
  const dims = boardJson.dimensions_mm ? `${boardJson.dimensions_mm[0]}×${boardJson.dimensions_mm[1]}mm` : 'unknown';

  const subject = `[Eisla] Manual order — ${fab} × ${quantity}`;
  const text = `Manufacturing order requires manual fulfilment.

Order ID:   ${orderId}
Design ID:  ${designId}
Fab:        ${fab}
Quantity:   ${quantity}
Board:      ${dims}, ${boardJson.layers || 2} layers

Shipping address:
${addr}

Files are in the job-artifacts Supabase Storage bucket under ${designId}/.
Download output.zip and place the order manually at ${getFabUrl(fab)}.
`;

  // Use Resend directly for operator notification
  const { Resend } = require('resend');
  const key = process.env.RESEND_API_KEY;
  if (!key || key === 're_xxx') {
    console.warn('[ordermanager] RESEND_API_KEY not configured — manual fulfilment email skipped');
    console.log(text); // Log it at minimum
    return;
  }

  try {
    const resend = new Resend(key);
    await resend.emails.send({
      from:    `Eisla Orders <${process.env.FROM_EMAIL || 'noreply@eisla.io'}>`,
      to:      [operatorEmail],
      subject,
      text,
    });
    console.log(`[ordermanager] Manual fulfilment email sent to ${operatorEmail}`);
  } catch (err) {
    console.error(`[ordermanager] Manual fulfilment email failed: ${err.message}`);
    console.log(text); // Log as fallback
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatShipping(shipping) {
  if (!shipping) return null;
  const a = shipping.address || {};
  const parts = [
    shipping.name,
    a.line1,
    a.line2,
    a.city,
    a.state,
    a.postal_code,
    a.country,
  ].filter(Boolean);
  return parts.join('\n');
}

function getFabUrl(fab) {
  const urls = {
    PCBTrain:     'https://www.pcbtrain.co.uk',
    PCBWay:       'https://www.pcbway.com',
    Eurocircuits: 'https://www.eurocircuits.com',
    JLCPCB:       'https://jlcpcb.com',
  };
  return urls[fab] || '';
}

// ─── Query order status ──────────────────────────────────────────────────────

async function getOrder(orderId) {
  const admin = supaAdmin();
  const { data, error } = await admin
    .from('manufacturing_orders')
    .select('*')
    .eq('id', orderId)
    .single();

  if (error) return null;
  return data;
}

async function getOrdersByDesign(designId) {
  const admin = supaAdmin();
  const { data, error } = await admin
    .from('manufacturing_orders')
    .select('id, fab, quantity, status, fab_order_ref, batch_number, customer_price_gbp, created_at')
    .eq('design_id', designId)
    .order('created_at', { ascending: false });

  if (error) return [];
  return data;
}

/**
 * updateOrderStatus(orderId, status, fields)
 * Called by internal/ops hub endpoints to update tracking info.
 */
async function updateOrderStatus(orderId, status, fields = {}) {
  const admin = supaAdmin();
  const { error } = await admin
    .from('manufacturing_orders')
    .update({ status, ...fields })
    .eq('id', orderId);

  if (error) throw new Error(`Order update failed: ${error.message}`);
}

module.exports = {
  placeOrder,
  getOrder,
  getOrdersByDesign,
  updateOrderStatus,
};
