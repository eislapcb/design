'use strict';

/**
 * Eisla — Customer Accounts (server/accounts.js)
 *
 * Uses Supabase Auth for authentication (shared project with ops hub).
 * Internal staff (admin/engineer/auditor) live in the ops hub `users` table.
 * Customer accounts are Supabase Auth users + a `customer_profiles` row.
 *
 * NIST password rules (mirroring ops hub src/lib/auth.ts):
 *   - 15–64 characters
 *   - Checked against HaveIBeenPwned (k-anonymity)
 *   - No complexity requirements
 */

const { createClient } = require('@supabase/supabase-js');
const crypto = require('crypto');

// ─── Supabase clients ─────────────────────────────────────────────────────────

// Anon client — used for sign-in/sign-up (respects RLS)
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
);

// Service-role client — used for server-side operations that bypass RLS
const supabaseAdmin = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

// ─── Password validation (NIST SP 800-63B) ────────────────────────────────────

/**
 * Validate password against NIST rules.
 * Returns { valid: true } or { valid: false, error: '...' }
 */
function validatePassword(password) {
  if (!password || password.length < 15) {
    return { valid: false, error: 'Password must be at least 15 characters' };
  }
  if (password.length > 64) {
    return { valid: false, error: 'Password must be 64 characters or fewer' };
  }
  return { valid: true };
}

/**
 * Check password against HaveIBeenPwned using k-anonymity model.
 * Returns true if the password appears in a breach, false if safe.
 */
async function isPwned(password) {
  try {
    const hash = crypto.createHash('sha1').update(password).digest('hex').toUpperCase();
    const prefix = hash.slice(0, 5);
    const suffix = hash.slice(5);

    const https = require('https');
    const data = await new Promise((resolve, reject) => {
      const req = https.get(`https://api.pwnedpasswords.com/range/${prefix}`, res => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => resolve(body));
      });
      req.on('error', reject);
      req.setTimeout(3000, () => { req.destroy(); reject(new Error('timeout')); });
    });

    return data.split('\r\n').some(line => line.split(':')[0] === suffix);
  } catch {
    // If HIBP is unreachable, fail open (don't block the user)
    return false;
  }
}

// ─── Customer profile helpers ─────────────────────────────────────────────────

/**
 * Create a customer_profiles row for a newly registered user.
 * The table is owned by the design system (not the ops hub).
 */
async function createProfile(userId, { name, email }) {
  const referralCode = crypto.randomBytes(4).toString('hex'); // e.g. "a3f9c2e1"

  const { error } = await supabaseAdmin
    .from('customer_profiles')
    .insert({
      id:            userId,   // matches auth.users.id
      name,
      email,
      credits:       0,
      referral_code: referralCode,
    });

  if (error) throw new Error(`Profile creation failed: ${error.message}`);
  return referralCode;
}

/**
 * Fetch the customer profile for an authenticated user.
 */
async function getProfile(userId) {
  const { data, error } = await supabaseAdmin
    .from('customer_profiles')
    .select('id, name, email, credits, referral_code, created_at')
    .eq('id', userId)
    .single();

  if (error) return null;
  return data;
}

// ─── Exported auth functions ──────────────────────────────────────────────────

/**
 * register({ name, email, password })
 * Creates a Supabase Auth user + customer_profiles row.
 * Returns { success, user?, error? }
 */
async function register({ name, email, password }) {
  // NIST length check
  const pw = validatePassword(password);
  if (!pw.valid) return { success: false, error: pw.error };

  // HIBP breach check
  const pwned = await isPwned(password);
  if (pwned) {
    return {
      success: false,
      error: 'This password has appeared in a data breach. Please choose a different password.',
    };
  }

  // Create Supabase Auth user
  const { data, error } = await supabase.auth.signUp({ email, password });
  if (error) return { success: false, error: error.message };

  const userId = data.user?.id;
  if (!userId) return { success: false, error: 'Registration failed — no user ID returned' };

  // Create profile
  try {
    const referralCode = await createProfile(userId, { name, email });
    return { success: true, user: { id: userId, name, email, referral_code: referralCode } };
  } catch (profileErr) {
    // Clean up the auth user if profile creation fails
    await supabaseAdmin.auth.admin.deleteUser(userId);
    return { success: false, error: profileErr.message };
  }
}

/**
 * login({ email, password })
 * Returns { success, session?, user?, profile?, error? }
 */
async function login({ email, password }) {
  const { data, error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) return { success: false, error: error.message };

  const profile = await getProfile(data.user.id);

  return {
    success: true,
    session: data.session,
    user:    data.user,
    profile,
  };
}

/**
 * logout(accessToken)
 * Signs the user out (invalidates the session server-side).
 */
async function logout(accessToken) {
  // Use an authed client to sign out the specific session
  const client = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    { global: { headers: { Authorization: `Bearer ${accessToken}` } } }
  );
  const { error } = await client.auth.signOut();
  return { success: !error, error: error?.message };
}

/**
 * getUser(accessToken)
 * Verify a JWT and return the user + profile. Used by auth middleware.
 * Returns { valid: true, user, profile } or { valid: false }
 */
async function getUser(accessToken) {
  const { data, error } = await supabaseAdmin.auth.getUser(accessToken);
  if (error || !data.user) return { valid: false };

  const profile = await getProfile(data.user.id);
  return { valid: true, user: data.user, profile };
}

/**
 * changePassword(accessToken, newPassword)
 */
async function changePassword(accessToken, newPassword) {
  const pw = validatePassword(newPassword);
  if (!pw.valid) return { success: false, error: pw.error };

  const pwned = await isPwned(newPassword);
  if (pwned) {
    return {
      success: false,
      error: 'This password has appeared in a data breach. Please choose a different password.',
    };
  }

  const client = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    { global: { headers: { Authorization: `Bearer ${accessToken}` } } }
  );

  const { error } = await client.auth.updateUser({ password: newPassword });
  if (error) return { success: false, error: error.message };
  return { success: true };
}

/**
 * requireAuth middleware for Express routes.
 * Reads Bearer token from Authorization header, validates it, attaches
 * req.user and req.profile. Returns 401 if missing/invalid.
 */
function requireAuth(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader?.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Authentication required' });
  }

  const token = authHeader.slice(7);
  getUser(token).then(result => {
    if (!result.valid) return res.status(401).json({ error: 'Invalid or expired token' });
    req.user    = result.user;
    req.profile = result.profile;
    next();
  }).catch(() => res.status(401).json({ error: 'Authentication error' }));
}

module.exports = { register, login, logout, getUser, changePassword, requireAuth, getProfile };
