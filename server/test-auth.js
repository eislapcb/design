'use strict';

/**
 * Quick smoke test for auth endpoints.
 * Run: node server/test-auth.js
 * Server must be running on port 3001.
 */

const http = require('http');

function request(method, path, body) {
  return new Promise((resolve, reject) => {
    const payload = body ? JSON.stringify(body) : null;
    const options = {
      hostname: 'localhost',
      port: 3001,
      path,
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(payload ? { 'Content-Length': Buffer.byteLength(payload) } : {}),
      },
    };
    const req = http.request(options, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(data) }));
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

async function run() {
  const pass = (label) => console.log(`  ✓  ${label}`);
  const fail = (label, got) => { console.error(`  ✗  ${label}`); console.error('     got:', JSON.stringify(got)); };
  let ok = 0, bad = 0;

  function check(label, condition, got) {
    if (condition) { pass(label); ok++; } else { fail(label, got); bad++; }
  }

  console.log('\n─── Auth endpoint smoke tests ───────────────────────────────\n');

  // 1. Health check
  {
    const r = await request('GET', '/api/health');
    check('GET /api/health → 200', r.status === 200, r);
  }

  // 2. Register — missing fields
  {
    const r = await request('POST', '/api/auth/register', { email: 'x@x.com' });
    check('POST /api/auth/register (missing fields) → 400', r.status === 400, r);
  }

  // 3. Register — password too short (NIST)
  {
    const r = await request('POST', '/api/auth/register', {
      name: 'Test', email: 'test@eisla.io', password: 'short',
    });
    check(
      'POST /api/auth/register (short password) → 400 + NIST error',
      r.status === 400 && r.body.success === false && r.body.error.includes('15 char'),
      r.body,
    );
  }

  // 4. Register — password too long (NIST)
  {
    const r = await request('POST', '/api/auth/register', {
      name: 'Test', email: 'test@eisla.io', password: 'a'.repeat(65),
    });
    check(
      'POST /api/auth/register (long password) → 400 + NIST error',
      r.status === 400 && r.body.success === false && r.body.error.includes('64 char'),
      r.body,
    );
  }

  // 5. Login — missing fields
  {
    const r = await request('POST', '/api/auth/login', { email: 'x@x.com' });
    check('POST /api/auth/login (missing fields) → 400', r.status === 400, r.body);
  }

  // 6. GET /api/auth/me — no token
  {
    const r = await request('GET', '/api/auth/me');
    check('GET /api/auth/me (no token) → 401', r.status === 401, r.body);
  }

  // 7. POST /api/auth/logout — no token
  {
    const r = await request('POST', '/api/auth/logout');
    check('POST /api/auth/logout (no token) → 401', r.status === 401, r.body);
  }

  // 8. POST /api/auth/change-password — no token
  {
    const r = await request('POST', '/api/auth/change-password', { newPassword: 'x'.repeat(20) });
    check('POST /api/auth/change-password (no token) → 401', r.status === 401, r.body);
  }

  console.log(`\n─────────────────────────────────────────────────────────────`);
  console.log(`  ${ok} passed  /  ${bad} failed\n`);
  if (bad > 0) process.exit(1);
}

run().catch(err => { console.error('Test runner error:', err.message); process.exit(1); });
