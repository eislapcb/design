'use strict';

/**
 * Eisla — Email Notifications (server/notifier.js)
 *
 * Session 13. Uses Resend (resend.com) for transactional email.
 * From: noreply@eisla.io (configurable via FROM_EMAIL env var).
 *
 * Email sends are best-effort — a failed send NEVER fails the pipeline.
 * All links use BASE_URL from .env — never hardcoded.
 * Every email includes both HTML and plain text.
 *
 * Email triggers:
 *   1. Job Created           — immediately after Stripe webhook creates design
 *   2. Placement Ready       — status → awaiting_placement_approval
 *   3. Design Complete       — status → files_ready
 *   4. Order Placed          — after manufacturing payment webhook
 *   5. Stock Alert           — at resolve time (future — Session 16+)
 */

const { Resend } = require('resend');

// ─── Config ──────────────────────────────────────────────────────────────────

const FROM      = process.env.FROM_EMAIL || 'noreply@eisla.io';
const FROM_LINE = `Eisla <${FROM}>`;
const BASE_URL  = process.env.BASE_URL   || 'http://localhost:3001';

let _resend;
function getResend() {
  if (!_resend) {
    const key = process.env.RESEND_API_KEY;
    if (!key || key === 're_xxx') return null;
    _resend = new Resend(key);
  }
  return _resend;
}

// ─── Send helper (best-effort) ───────────────────────────────────────────────

async function send(to, subject, html, text) {
  const resend = getResend();
  if (!resend) {
    console.warn('[notifier] RESEND_API_KEY not configured — email skipped');
    return false;
  }
  if (!to) {
    console.warn('[notifier] No recipient email — skipped');
    return false;
  }

  try {
    const { data, error } = await resend.emails.send({
      from:    FROM_LINE,
      to:      [to],
      subject,
      html,
      text,
    });

    if (error) {
      console.error(`[notifier] Resend error: ${error.message}`);
      return false;
    }

    console.log(`[notifier] Sent "${subject}" to ${to} — id=${data?.id}`);
    return true;
  } catch (err) {
    console.error(`[notifier] Send failed: ${err.message}`);
    return false;
  }
}

// ─── HTML wrapper ────────────────────────────────────────────────────────────

function wrap(bodyHtml) {
  return `<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#FDF8F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#FDF8F0;">
<tr><td align="center" style="padding:40px 20px;">
<table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">

<!-- Header -->
<tr><td style="background:#0E3D3F;padding:24px 32px;">
  <span style="color:#C27840;font-size:24px;font-weight:700;letter-spacing:0.5px;">Eisla</span>
  <span style="color:#FFFFFF;font-size:14px;margin-left:12px;opacity:0.8;">From words to boards</span>
</td></tr>

<!-- Body -->
<tr><td style="padding:32px;color:#1A1A1A;font-size:15px;line-height:1.6;">
${bodyHtml}
</td></tr>

<!-- Footer -->
<tr><td style="padding:20px 32px;background:#F5F1EB;font-size:12px;color:#666666;text-align:center;">
  Eisla &mdash; PCB design, simplified.<br>
  <a href="${BASE_URL}" style="color:#C27840;text-decoration:none;">${BASE_URL.replace(/^https?:\/\//, '')}</a>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>`;
}

function button(href, label) {
  return `<table cellpadding="0" cellspacing="0" style="margin:24px 0;"><tr>
<td style="background:#C27840;border-radius:6px;padding:12px 28px;">
  <a href="${href}" style="color:#FFFFFF;text-decoration:none;font-weight:600;font-size:15px;">${label}</a>
</td>
</tr></table>`;
}

// ─── 1. Job Created ──────────────────────────────────────────────────────────

async function sendJobCreatedEmail({ to, name, designId }) {
  const shortId = designId.slice(0, 8);
  const subject = 'Your PCB design is being generated — Eisla';

  const html = wrap(`
<p>Hi ${name || 'there'},</p>
<p>Your design job has started. We'll email you when it's ready (usually 2–5 minutes).</p>
<p style="font-family:'JetBrains Mono',Consolas,'Courier New',monospace;color:#666666;font-size:13px;">
  Job reference: ${shortId}
</p>
${button(`${BASE_URL}/jobs/${designId}`, 'Track progress')}
<p style="color:#666666;font-size:13px;">You can close this tab — we'll email you at each step.</p>
`);

  const text = `Hi ${name || 'there'},

Your design job has started. We'll email you when it's ready (usually 2-5 minutes).

Job reference: ${shortId}
Track progress: ${BASE_URL}/jobs/${designId}

You can close this tab - we'll email you at each step.`;

  return send(to, subject, html, text);
}

// ─── 2. Placement Ready ─────────────────────────────────────────────────────

async function sendPlacementReadyEmail({ to, name, designId }) {
  const subject = 'Review your component layout — action needed';

  const html = wrap(`
<p>Hi ${name || 'there'},</p>
<p>Your component placement is ready to review.</p>
${button(`${BASE_URL}/jobs/${designId}`, 'View placement →')}
<p style="color:#666666;font-size:13px;">
  If you don't review within 24 hours, we'll approve it automatically and continue routing.
</p>
`);

  const text = `Hi ${name || 'there'},

Your component placement is ready to review.

View placement: ${BASE_URL}/jobs/${designId}

If you don't review within 24 hours, we'll approve it automatically and continue routing.`;

  return send(to, subject, html, text);
}

// ─── 3. Design Complete (files_ready) ────────────────────────────────────────

async function sendFilesReadyEmail({ to, name, designId }) {
  const subject = 'Your PCB design is ready to download';

  const html = wrap(`
<p>Hi ${name || 'there'},</p>
<p>Your design is complete. Your files are ready and manufacturing quotes are waiting.</p>
${button(`${BASE_URL}/jobs/${designId}`, 'Download files →')}
<p>
  <a href="${BASE_URL}/jobs/${designId}#quotes" style="color:#C27840;text-decoration:none;font-weight:600;">
    View manufacturing quotes →
  </a>
</p>
<p style="color:#666666;font-size:13px;">
  Files expire in 24 hours. Log in to your account to save them permanently.
</p>
`);

  const text = `Hi ${name || 'there'},

Your design is complete. Your files are ready and manufacturing quotes are waiting.

Download files: ${BASE_URL}/jobs/${designId}
View manufacturing quotes: ${BASE_URL}/jobs/${designId}#quotes

Files expire in 24 hours. Log in to your account to save them permanently.`;

  return send(to, subject, html, text);
}

// ─── 4. Manufacturing Order Placed ───────────────────────────────────────────

async function sendOrderPlacedEmail({ to, name, fab, quantity, estimatedDays, orderRef }) {
  const subject = `Manufacturing order confirmed — ${fab}`;

  const html = wrap(`
<p>Hi ${name || 'there'},</p>
<p>We've placed your order with <strong>${fab}</strong>.</p>
<table style="margin:16px 0;font-size:14px;">
  <tr><td style="padding:4px 16px 4px 0;color:#666666;">Quantity</td><td>${quantity} board${quantity > 1 ? 's' : ''}</td></tr>
  ${estimatedDays ? `<tr><td style="padding:4px 16px 4px 0;color:#666666;">Estimated delivery</td><td>${estimatedDays} working days</td></tr>` : ''}
  ${orderRef ? `<tr><td style="padding:4px 16px 4px 0;color:#666666;">Order reference</td><td style="font-family:'JetBrains Mono',Consolas,'Courier New',monospace;">${orderRef}</td></tr>` : ''}
</table>
<p>We'll email you again when it ships.</p>
`);

  const text = `Hi ${name || 'there'},

We've placed your order with ${fab}.

Quantity: ${quantity} board${quantity > 1 ? 's' : ''}${estimatedDays ? `\nEstimated delivery: ${estimatedDays} working days` : ''}${orderRef ? `\nOrder reference: ${orderRef}` : ''}

We'll email you again when it ships.`;

  return send(to, subject, html, text);
}

// ─── 5. Stock Alert ──────────────────────────────────────────────────────────

async function sendStockAlertEmail({ to, name, designId, component, status, leadTime, alternative }) {
  const subject = 'Stock alert for your PCB design';

  const altBlock = alternative
    ? `<p><strong>${alternative}</strong> is available and compatible.</p>
       ${button(`${BASE_URL}/jobs/${designId}?swap=${encodeURIComponent(component)}`, 'Swap to alternative →')}`
    : '';

  const html = wrap(`
<p>Hi ${name || 'there'},</p>
<p>One component in your design is currently out of stock:</p>
<p style="font-family:'JetBrains Mono',Consolas,'Courier New',monospace;background:#FDF8F0;padding:12px;border-radius:4px;">
  <strong>${component}</strong> — ${status}${leadTime ? ` — ${leadTime}` : ''}
</p>
${altBlock}
<p style="color:#666666;font-size:13px;">
  You can still proceed with the original component — just be aware of availability before ordering.
</p>
`);

  const text = `Hi ${name || 'there'},

One component in your design is currently out of stock:

${component} — ${status}${leadTime ? ` — ${leadTime}` : ''}
${alternative ? `\n${alternative} is available and compatible.\nSwap: ${BASE_URL}/jobs/${designId}?swap=${encodeURIComponent(component)}` : ''}

You can still proceed with the original component - just be aware of availability before ordering.`;

  return send(to, subject, html, text);
}

// ─── Convenience: look up customer email from design ─────────────────────────

async function getCustomerInfo(designId) {
  const { createClient } = require('@supabase/supabase-js');
  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
  );

  const { data: design } = await admin
    .from('designs')
    .select('customer_id')
    .eq('id', designId)
    .single();

  if (!design?.customer_id) return null;

  const { data: profile } = await admin
    .from('customer_profiles')
    .select('name, email')
    .eq('id', design.customer_id)
    .single();

  return profile || null;
}

/**
 * Notify a customer by designId. Looks up customer email from Supabase.
 * type: 'job_created' | 'placement_ready' | 'files_ready'
 */
async function notifyCustomer(designId, type) {
  try {
    const customer = await getCustomerInfo(designId);
    if (!customer) {
      console.warn(`[notifier] No customer info for design ${designId} — email skipped`);
      return false;
    }

    const params = { to: customer.email, name: customer.name, designId };

    switch (type) {
      case 'job_created':
        return sendJobCreatedEmail(params);
      case 'placement_ready':
        return sendPlacementReadyEmail(params);
      case 'files_ready':
        return sendFilesReadyEmail(params);
      default:
        console.warn(`[notifier] Unknown notification type: ${type}`);
        return false;
    }
  } catch (err) {
    console.error(`[notifier] notifyCustomer failed: ${err.message}`);
    return false;
  }
}

/**
 * Look up customer info from a Stripe session's metadata (has user_id).
 * Used by stripe.js webhook handlers for manufacturing/credit emails.
 */
async function getCustomerInfoFromMetadata(session) {
  const userId = session.metadata?.user_id;
  if (!userId) return null;

  const { createClient } = require('@supabase/supabase-js');
  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
  );

  const { data: profile } = await admin
    .from('customer_profiles')
    .select('name, email')
    .eq('id', userId)
    .single();

  return profile || null;
}

module.exports = {
  sendJobCreatedEmail,
  sendPlacementReadyEmail,
  sendFilesReadyEmail,
  sendOrderPlacedEmail,
  sendStockAlertEmail,
  notifyCustomer,
  getCustomerInfoFromMetadata,
};
