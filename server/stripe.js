'use strict';

/**
 * Eisla — Stripe Integration (server/stripe.js)
 *
 * Three separate Stripe Checkout flows — identified by metadata.type:
 *   'design_fee'        — customer pays for a new PCB design
 *   'manufacturing'     — customer pays to manufacture a completed design
 *   'credit_purchase'   — customer buys a credit pack
 *
 * CRITICAL SECURITY RULES (from BRIEF.md):
 *   - Jobs must ONLY be created from the Stripe webhook — never from the success URL.
 *     The redirect URL can be spoofed; the webhook signature cannot.
 *   - The webhook route must receive the raw request body (express.raw).
 *     It is registered in index.js BEFORE express.json() middleware.
 *   - Raw fab prices must NEVER be returned by the /api/jobs/:id/quotes endpoint.
 *   - Quote expiry must be enforced at manufacturing checkout (reject >24h old quotes).
 *   - Credit redemption must be atomic (Supabase transaction) to prevent double-spend.
 *   - Three Stripe flows exist — never conflate them. Each identified by metadata.type.
 */

const Stripe  = require('stripe');
const { v4: uuidv4 } = require('uuid');
const { getDesignFee, getServiceSurchargePence, applyMarginPence } = require('./pricing');
const notifier     = require('./notifier');
const ordermanager = require('./ordermanager');

// ─── Stripe client ────────────────────────────────────────────────────────────

function getStripe() {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key || key === 'sk_test_xxx') {
    throw new Error('STRIPE_SECRET_KEY not configured');
  }
  return new Stripe(key, { apiVersion: '2024-06-20' });
}

const BASE_URL = process.env.BASE_URL || 'http://localhost:3001';

// ─── Flow 1: Design fee checkout ──────────────────────────────────────────────

/**
 * createDesignCheckout(options)
 *
 * Creates a Stripe Checkout session for the design fee.
 * Returns { url, sessionId }
 *
 * options: {
 *   tier            — 1, 2, or 3
 *   repeat_customer — bool
 *   promo           — bool
 *   service_level   — 'standard' | 'priority' | 'express'
 *   boardConfig     — full board config object (stored in metadata)
 *   capabilities    — string[] (stored in metadata)
 *   userId          — string | null
 *   userEmail       — string | null
 * }
 */
async function createDesignCheckout({
  tier,
  repeat_customer = false,
  promo = false,
  service_level = 'standard',
  boardConfig,
  capabilities,
  userId = null,
  userEmail = null,
}) {
  const stripe = getStripe();

  const design_fee_pence    = getDesignFee(tier, { repeat_customer, promo });
  const service_pence       = getServiceSurchargePence(service_level);
  const total_pence         = design_fee_pence + service_pence;

  const sessionId = uuidv4(); // our internal job-correlation ID (not the Stripe session ID)

  const params = {
    mode: 'payment',
    payment_method_types: ['card'],
    line_items: [
      {
        price_data: {
          currency:     'gbp',
          unit_amount:  design_fee_pence,
          product_data: {
            name:        `Eisla PCB Design — Tier ${tier}`,
            description: `${repeat_customer ? 'Repeat customer discount applied. ' : ''}Board design, component selection, routing, and manufacturing files.`,
          },
        },
        quantity: 1,
      },
      ...(service_pence > 0 ? [{
        price_data: {
          currency:    'gbp',
          unit_amount: service_pence,
          product_data: {
            name:        `${service_level.charAt(0).toUpperCase() + service_level.slice(1)} Service`,
            description: `${service_level === 'priority' ? 'Priority processing (+£50)' : 'Express processing (+£150)'}`,
          },
        },
        quantity: 1,
      }] : []),
    ],
    metadata: {
      type:            'design_fee',
      correlation_id:  sessionId,
      tier:            String(tier),
      repeat_customer: String(repeat_customer),
      promo:           String(promo),
      service_level,
      user_id:         userId || '',
      capabilities:    JSON.stringify(capabilities || []),
      board_config:    JSON.stringify(boardConfig  || {}),
    },
    customer_email:  userEmail || undefined,
    success_url:     `${BASE_URL}/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url:      `${BASE_URL}/wizard`,
    automatic_tax:   { enabled: true },
  };

  const session = await stripe.checkout.sessions.create(params);
  return { url: session.url, sessionId: session.id, correlationId: sessionId };
}

// ─── Flow 2: Manufacturing order checkout ─────────────────────────────────────

/**
 * createManufacturingCheckout(options)
 *
 * Creates a Stripe Checkout session for the manufacturing order.
 * Enforces 24-hour quote expiry.
 * Returns { url, sessionId }
 *
 * options: {
 *   jobId          — UUID of the completed design job
 *   fab            — 'PCBTrain' | 'PCBWay' | 'Eurocircuits' | 'JLCPCB'
 *   quantity       — integer
 *   rawPriceGbp    — number (internal, not shown to customer)
 *   jobType        — 'new' | 'reorder'
 *   quoteGeneratedAt — ISO timestamp of when the quote was generated
 *   userId         — string | null
 *   userEmail      — string | null
 * }
 */
async function createManufacturingCheckout({
  jobId,
  fab,
  quantity,
  rawPriceGbp,
  jobType = 'new',
  quoteGeneratedAt,
  userId = null,
  userEmail = null,
}) {
  // Enforce 24-hour quote expiry
  if (quoteGeneratedAt) {
    const quoteAge = Date.now() - new Date(quoteGeneratedAt).getTime();
    const TWENTY_FOUR_HOURS = 24 * 60 * 60 * 1000;
    if (quoteAge > TWENTY_FOUR_HOURS) {
      throw new Error('Quote has expired. Please refresh the manufacturing quotes before ordering.');
    }
  }

  const stripe = getStripe();

  const rawPencePer      = Math.round(rawPriceGbp * 100);
  const customerPence    = applyMarginPence(rawPencePer, jobType, quantity);
  const customerPriceGbp = (customerPence / 100).toFixed(2);

  const session = await stripe.checkout.sessions.create({
    mode: 'payment',
    payment_method_types: ['card'],
    line_items: [{
      price_data: {
        currency:    'gbp',
        unit_amount: customerPence,
        product_data: {
          name:        `${quantity}x PCB from ${fab}`,
          description: `Manufacturing order for job ${jobId}. ${jobType === 'reorder' ? 'Reorder — 10% discount applied.' : ''}`,
        },
      },
      quantity: 1,
    }],
    metadata: {
      type:          'manufacturing',
      job_id:        jobId,
      fab,
      quantity:      String(quantity),
      job_type:      jobType,
      customer_price_gbp: customerPriceGbp,
      // raw_price deliberately NOT stored in metadata — internal only
      user_id:       userId || '',
    },
    customer_email:           userEmail || undefined,
    // Collect shipping address for the fab order
    shipping_address_collection: {
      allowed_countries: ['GB', 'US', 'DE', 'FR', 'NL', 'SE', 'NO', 'DK', 'FI', 'BE', 'AU', 'CA'],
    },
    success_url: `${BASE_URL}/order-confirmed?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url:  `${BASE_URL}/jobs/${jobId}`,
    automatic_tax: { enabled: true },
  });

  return { url: session.url, sessionId: session.id };
}

// ─── Flow 3: Credit pack checkout ────────────────────────────────────────────

const CREDIT_PACKS = {
  1: { credits: 1, price_pence: 4990,  label: '1 design credit — £49.90' },
  3: { credits: 3, price_pence: 13490, label: '3 design credits — £134.90 (save 10%)' },
  5: { credits: 5, price_pence: 19990, label: '5 design credits — £199.90 (save 20%)' },
};

/**
 * createCreditCheckout(options)
 * options: { packSize: 1|3|5, userId, userEmail }
 */
async function createCreditCheckout({ packSize, userId = null, userEmail = null }) {
  const stripe = getStripe();
  const pack   = CREDIT_PACKS[packSize];
  if (!pack) throw new Error(`Unknown credit pack size: ${packSize}`);

  const session = await stripe.checkout.sessions.create({
    mode: 'payment',
    payment_method_types: ['card'],
    line_items: [{
      price_data: {
        currency:    'gbp',
        unit_amount: pack.price_pence,
        product_data: {
          name:        pack.label,
          description: `${pack.credits} Eisla design credit${pack.credits > 1 ? 's' : ''}. Credits never expire.`,
        },
      },
      quantity: 1,
    }],
    metadata: {
      type:    'credit_purchase',
      pack_size:   String(packSize),
      credits: String(pack.credits),
      user_id: userId || '',
    },
    customer_email: userEmail || undefined,
    success_url: `${BASE_URL}/account/credits?purchased=true`,
    cancel_url:  `${BASE_URL}/account/credits`,
    automatic_tax: { enabled: true },
  });

  return { url: session.url, sessionId: session.id };
}

// ─── Webhook handler ──────────────────────────────────────────────────────────

/**
 * handleWebhook(req, res)
 *
 * Express route handler for POST /api/webhook.
 * MUST be registered BEFORE express.json() in index.js — uses express.raw().
 * Verifies Stripe signature, then dispatches to the appropriate handler.
 */
async function handleWebhook(req, res) {
  const sig    = req.headers['stripe-signature'];
  const secret = process.env.STRIPE_WEBHOOK_SECRET;

  if (!secret || secret === 'whsec_xxx') {
    console.error('[webhook] STRIPE_WEBHOOK_SECRET not configured');
    return res.status(500).json({ error: 'Webhook secret not configured' });
  }

  let event;
  try {
    const stripe = getStripe();
    event = stripe.webhooks.constructEvent(req.body, sig, secret);
  } catch (err) {
    console.error('[webhook] Signature verification failed:', err.message);
    return res.status(400).json({ error: `Webhook signature error: ${err.message}` });
  }

  console.log(`[webhook] ${event.type} id=${event.id}`);

  try {
    switch (event.type) {
      case 'checkout.session.completed':
        await handleCheckoutCompleted(event.data.object);
        break;
      case 'checkout.session.expired':
        // Log and ignore — job was never created so nothing to clean up
        console.log(`[webhook] Session expired: ${event.data.object.id}`);
        break;
      default:
        // Unhandled event types — acknowledge and ignore
        console.log(`[webhook] Unhandled event type: ${event.type}`);
    }
    res.json({ received: true });
  } catch (err) {
    console.error('[webhook] Handler error:', err);
    // Return 200 so Stripe doesn't retry — log the error for manual investigation
    res.json({ received: true, warning: 'Handler error — check server logs' });
  }
}

/**
 * handleCheckoutCompleted(session)
 * Dispatches to the correct handler based on metadata.type.
 */
async function handleCheckoutCompleted(session) {
  const type = session.metadata?.type;

  switch (type) {
    case 'design_fee':
      await handleDesignFeePaid(session);
      break;
    case 'manufacturing':
      await handleManufacturingPaid(session);
      break;
    case 'credit_purchase':
      await handleCreditPurchased(session);
      break;
    default:
      console.warn(`[webhook] checkout.session.completed with unknown type: ${type}`, session.id);
  }
}

// ─── Design fee paid ──────────────────────────────────────────────────────────

async function handleDesignFeePaid(session) {
  const { correlation_id, tier, user_id, capabilities, board_config, service_level } = session.metadata;

  console.log(`[webhook] Design fee paid — correlation_id=${correlation_id} tier=${tier}`);

  // Idempotency: check if job already created for this session
  // (Stripe may retry webhooks — check Supabase designs table)
  const { supabaseAdmin } = require('./accounts');

  const { data: existing } = await supabaseAdmin
    .from('designs')
    .select('id')
    .eq('stripe_session_id', session.id)
    .maybeSingle();

  if (existing) {
    console.log(`[webhook] Duplicate webhook — design already exists for session ${session.id}`);
    return;
  }

  // Parse stored metadata
  let capList   = [];
  let boardCfg  = {};
  try { capList  = JSON.parse(capabilities || '[]'); } catch {}
  try { boardCfg = JSON.parse(board_config || '{}'); } catch {}

  // Create the design record in Supabase
  const { data: design, error } = await supabaseAdmin
    .from('designs')
    .insert({
      customer_id:       user_id || null,
      description:       boardCfg.description || null,
      capabilities:      capList,
      tier:              parseInt(tier, 10),
      service_level:     service_level || 'standard',
      design_fee_gbp:    session.amount_total, // pence
      status:            'paid',
      stripe_session_id: session.id,
    })
    .select()
    .single();

  if (error) {
    throw new Error(`Failed to create design record: ${error.message}`);
  }

  console.log(`[webhook] Design created — id=${design.id} status=paid`);

  // Enqueue processing job in BullMQ (requires Redis)
  const { enqueue } = require('./queue');
  const queued = await enqueue('process_design', { designId: design.id });
  if (queued) {
    console.log(`[webhook] Enqueued process_design for ${design.id}`);
  } else {
    console.warn(`[webhook] Could not enqueue — Redis unavailable. Design ${design.id} must be processed manually.`);
  }

  // Best-effort "job created" email
  notifier.notifyCustomer(design.id, 'job_created').catch(() => {});
}

// ─── Manufacturing payment paid ───────────────────────────────────────────────

async function handleManufacturingPaid(session) {
  const { job_id, fab, quantity, customer_price_gbp, user_id } = session.metadata;
  const shipping = session.shipping_details;
  const qty = parseInt(quantity, 10);

  console.log(`[webhook] Manufacturing paid — job_id=${job_id} fab=${fab} qty=${qty}`);

  // Look up raw price from fab_quotes.json for the internal record
  let rawPriceGbp = null;
  try {
    const fs = require('fs');
    const path = require('path');
    const quotesPath = path.join(
      path.resolve(process.env.JOBS_DIR || './jobs'),
      job_id,
      'fab_quotes.json'
    );
    if (fs.existsSync(quotesPath)) {
      const fabQuotes = JSON.parse(fs.readFileSync(quotesPath, 'utf8'));
      const fabQuote = (fabQuotes.quotes || []).find(q => q.fab === fab);
      if (fabQuote?.quotes?.[qty]) {
        rawPriceGbp = fabQuote.quotes[qty].raw_gbp;
      }
    }
  } catch {} // non-critical

  // Place the manufacturing order
  const orderResult = await ordermanager.placeOrder({
    designId:         job_id,
    fab,
    quantity:         qty,
    customerPriceGbp: parseFloat(customer_price_gbp) || null,
    rawPriceGbp,
    stripeSessionId:  session.id,
    userId:           user_id || null,
    shipping,
  });

  console.log(`[webhook] Order ${orderResult.orderId} — status: ${orderResult.status}`);

  // Best-effort "order placed" email
  try {
    const info = await notifier.getCustomerInfoFromMetadata(session);
    if (info) {
      notifier.sendOrderPlacedEmail({
        to:       info.email,
        name:     info.name,
        fab,
        quantity: qty,
        orderRef: orderResult.fabOrderRef || null,
      }).catch(() => {});
    }
  } catch {} // best-effort
}

// ─── Credit pack purchased ────────────────────────────────────────────────────

async function handleCreditPurchased(session) {
  const { user_id, credits, pack_size } = session.metadata;

  if (!user_id) {
    console.error('[webhook] Credit purchase with no user_id — cannot apply credits');
    return;
  }

  console.log(`[webhook] Credit purchase — user_id=${user_id} credits=${credits}`);

  const { supabaseAdmin } = require('./accounts');

  // Idempotency: check if credits already applied for this session
  const { data: existing } = await supabaseAdmin
    .from('credit_ledger')
    .select('id')
    .eq('reference_id', session.id)
    .maybeSingle();

  if (existing) {
    console.log(`[webhook] Duplicate webhook — credits already applied for session ${session.id}`);
    return;
  }

  const creditsToAdd = parseInt(credits, 10);

  // Add to credit ledger
  const { error: ledgerError } = await supabaseAdmin
    .from('credit_ledger')
    .insert({
      customer_id:  user_id,
      delta:        creditsToAdd,
      reason:       'purchase',
      reference_id: session.id, // Stripe session ID as reference
    });

  if (ledgerError) throw new Error(`Credit ledger insert failed: ${ledgerError.message}`);

  // Update balance on customer_profiles
  const { data: profile } = await supabaseAdmin
    .from('customer_profiles')
    .select('credits')
    .eq('id', user_id)
    .single();

  if (profile) {
    await supabaseAdmin
      .from('customer_profiles')
      .update({ credits: (profile.credits || 0) + creditsToAdd })
      .eq('id', user_id);
  }

  console.log(`[webhook] +${creditsToAdd} credits applied to user ${user_id}`);
}

// ─── Exports ──────────────────────────────────────────────────────────────────

module.exports = {
  createDesignCheckout,
  createManufacturingCheckout,
  createCreditCheckout,
  handleWebhook,
  CREDIT_PACKS,
};
