#!/usr/bin/env node
/**
 * Eisla — End-to-End Pipeline Test
 *
 * Tests the full design pipeline:
 *   1. Register / login a test user
 *   2. Dev-mode checkout (creates design + enqueues pipeline)
 *   3. Poll until pipeline reaches awaiting_engineer_review (T2)
 *   4. Approve engineer review
 *   5. Poll until awaiting_placement_approval
 *   6. Approve placement
 *   7. Poll until files_ready
 *   8. Verify all expected artifacts exist on disk
 *   9. Verify Supabase Storage has artifacts
 *  10. Verify schematic + SVG have content
 *
 * Usage: node test-e2e-pipeline.js
 * Requires: API server on :3001, worker running, Redis running
 */

'use strict';

require('dotenv').config();
const fs   = require('fs');
const path = require('path');
const { createClient } = require('@supabase/supabase-js');

const API      = 'http://localhost:3001';
const SB_URL   = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SB_KEY   = process.env.SUPABASE_SERVICE_ROLE_KEY;
const JOBS_DIR = path.resolve(process.env.JOBS_DIR || './jobs');

const sb = createClient(SB_URL, SB_KEY);

// ── Helpers ─────────────────────────────────────────────────────────────────

let passed = 0, failed = 0;

function ok(msg) { passed++; console.log(`  \x1b[32m✓\x1b[0m ${msg}`); }
function fail(msg, detail) {
  failed++;
  console.log(`  \x1b[31m✗\x1b[0m ${msg}`);
  if (detail) console.log(`    ${detail}`);
}
function assert(cond, msg, detail) { cond ? ok(msg) : fail(msg, detail); }

async function api(method, path, body, headers = {}) {
  const opts = { method, headers: { 'Content-Type': 'application/json', ...headers } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${API}${path}`, opts);
  const json = await res.json().catch(() => ({}));
  return { status: res.status, ok: res.ok, json };
}

async function poll(fn, timeoutMs = 120_000, intervalMs = 2_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = fn();
    const val = result instanceof Promise ? await result : result;
    if (val) return val;
    await new Promise(r => setTimeout(r, intervalMs));
  }
  return null;
}

async function getDesignStatus(designId) {
  const { data } = await sb.from('designs').select('status').eq('id', designId).single();
  return data?.status;
}

// ── Test ────────────────────────────────────────────────────────────────────

async function main() {
  console.log('\n\x1b[1m═══ Eisla E2E Pipeline Test ═══\x1b[0m\n');

  // ── Step 1: Health check ────────────────────────────────────────────────
  console.log('\x1b[36m1. Health check\x1b[0m');
  const health = await api('GET', '/api/health');
  assert(health.ok, 'API server healthy', JSON.stringify(health.json));

  // ── Step 2: Register / login test user ──────────────────────────────────
  console.log('\x1b[36m2. Auth\x1b[0m');
  const email = `e2e-test-${Date.now()}@eisla.test`;
  const password = 'E2eTestPassword2026!';

  const reg = await api('POST', '/api/auth/register', { name: 'E2E Test', email, password });
  assert(reg.ok || reg.status === 409, `Register user (${reg.status})`, reg.json?.error);

  const login = await api('POST', '/api/auth/login', { email, password });
  assert(login.ok, 'Login', login.json?.error);
  const token = login.json?.session?.access_token;
  assert(!!token, 'Got access token');
  const authHeader = { Authorization: `Bearer ${token}` };

  // ── Step 3: Dev-mode checkout ───────────────────────────────────────────
  console.log('\x1b[36m3. Checkout (dev mode)\x1b[0m');
  const checkout = await api('POST', '/api/checkout', {
    tier: 2,
    capabilities: ['wifi', 'sense_water_level', 'led_single', 'power_usb'],
    boardConfig: { dimensions_mm: [100, 80], layers: 4, power_source: 'usb' },
    repeat_customer: false,
  }, authHeader);
  assert(checkout.ok, 'Dev checkout created design', checkout.json?.error);
  const designId = checkout.json?.designId;
  assert(!!designId, `Got designId: ${designId?.slice(0, 8)}`);

  if (!designId) {
    console.log('\n\x1b[31mCannot continue without designId\x1b[0m\n');
    process.exit(1);
  }

  // ── Step 4: Verify design in DB ─────────────────────────────────────────
  console.log('\x1b[36m4. Verify design in DB\x1b[0m');
  const { data: design } = await sb.from('designs')
    .select('id, status, capabilities, tier')
    .eq('id', designId).single();
  assert(design?.tier === 2, `Tier is 2 (got ${design?.tier})`);
  assert(Array.isArray(design?.capabilities) && design.capabilities.length === 4,
    `Capabilities stored (${design?.capabilities?.length})`);

  // ── Step 5: Wait for pipeline → awaiting_engineer_review ────────────────
  console.log('\x1b[36m5. Pipeline: intake → validate → schematic → ERC → netlist → place → PCB → SVG\x1b[0m');
  const reachedReview = await poll(async () => {
    const s = await getDesignStatus(designId);
    process.stdout.write(`    status: ${s}          \r`);
    return s === 'awaiting_engineer_review' || s === 'failed' ? s : null;
  }, 180_000, 2_000);
  console.log('');  // clear the \r line
  assert(reachedReview === 'awaiting_engineer_review',
    `Reached awaiting_engineer_review (got: ${reachedReview})`);

  if (reachedReview === 'failed') {
    console.log('\n\x1b[31mPipeline failed. Check worker logs.\x1b[0m\n');
    printResults();
    process.exit(1);
  }

  // ── Step 6: Verify local job artifacts ──────────────────────────────────
  console.log('\x1b[36m6. Verify local job files\x1b[0m');
  const jobDir = path.join(JOBS_DIR, designId);
  const expectedFiles = [
    'resolved.json', 'board.json', 'netlist.json', 'board.kicad_sch',
    'board.kicad_pcb', 'board.kicad_pro', 'board.kicad_prl',
    'placement.json', 'placement_preview.svg', 'board-erc.rpt',
  ];
  for (const f of expectedFiles) {
    const fp = path.join(jobDir, f);
    const exists = fs.existsSync(fp);
    const size = exists ? fs.statSync(fp).size : 0;
    assert(exists && size > 0, `${f} exists (${size} bytes)`, exists ? '' : 'MISSING');
  }

  // ── Step 7: Verify resolved components ──────────────────────────────────
  console.log('\x1b[36m7. Verify resolved components\x1b[0m');
  const resolved = JSON.parse(fs.readFileSync(path.join(jobDir, 'resolved.json'), 'utf8'));
  const comps = resolved.resolved_components || [];
  assert(comps.length > 0, `Resolved ${comps.length} components`);
  // Check for MCU
  const hasMcu = comps.some(c => c.component_id?.includes('esp32'));
  assert(hasMcu, 'ESP32 MCU resolved');

  // ── Step 8: Verify schematic has content (hierarchical sheets) ──────────
  console.log('\x1b[36m8. Verify schematic content\x1b[0m');
  const schContent = fs.readFileSync(path.join(jobDir, 'board.kicad_sch'), 'utf8');
  assert(schContent.includes('(sheet'), 'Top-level schematic has hierarchical sheet references');
  // Find sub-sheet files referenced in the top-level schematic
  const sheetFileRe = /Sheetfile"\s+"([^"]+\.kicad_sch)"/g;
  const subSheets = [...schContent.matchAll(sheetFileRe)].map(m => m[1]);
  assert(subSheets.length > 0, `Found ${subSheets.length} hierarchical sub-sheets`);
  // Verify sub-sheets have real content (symbols + lib_symbols)
  let totalSchLines = 0;
  let hasSymbol = false, hasLibSymbols = false;
  for (const sf of subSheets) {
    const sfPath = path.join(jobDir, sf);
    const exists = fs.existsSync(sfPath);
    assert(exists, `Sub-sheet ${sf} exists`);
    if (exists) {
      const sub = fs.readFileSync(sfPath, 'utf8');
      totalSchLines += sub.split('\n').length;
      if (sub.includes('(symbol')) hasSymbol = true;
      if (sub.includes('lib_symbols')) hasLibSymbols = true;
    }
  }
  assert(totalSchLines > 100, `Sub-sheets total ${totalSchLines} lines (>100)`);
  assert(hasSymbol, 'Sub-sheets contain symbol instances');
  assert(hasLibSymbols, 'Sub-sheets contain lib_symbols section');

  // ── Step 9: Verify SVG has components ───────────────────────────────────
  console.log('\x1b[36m9. Verify SVG preview\x1b[0m');
  const svgContent = fs.readFileSync(path.join(jobDir, 'placement_preview.svg'), 'utf8');
  assert(svgContent.includes('<rect'), 'SVG contains component rectangles');
  assert(svgContent.includes('<text'), 'SVG contains text labels');
  const svgSize = svgContent.length;
  assert(svgSize > 2000, `SVG has substance (${svgSize} bytes)`);

  // ── Step 10: Verify netlist ─────────────────────────────────────────────
  console.log('\x1b[36m10. Verify netlist\x1b[0m');
  const netlist = JSON.parse(fs.readFileSync(path.join(jobDir, 'netlist.json'), 'utf8'));
  assert(netlist.net_count > 0, `Netlist has ${netlist.net_count} nets`);
  assert(Object.keys(netlist.nets).some(n => n.includes('GND')), 'Netlist has GND net');

  // ── Step 11: Verify KiCad PCB file ──────────────────────────────────────
  console.log('\x1b[36m11. Verify KiCad PCB\x1b[0m');
  const pcbContent = fs.readFileSync(path.join(jobDir, 'board.kicad_pcb'), 'utf8');
  assert(pcbContent.includes('(kicad_pcb'), 'PCB file has kicad_pcb header');
  assert(pcbContent.includes('(footprint'), 'PCB file has footprint instances');
  const pcbLines = pcbContent.split('\n').length;
  assert(pcbLines > 100, `PCB has ${pcbLines} lines (>100)`);

  // ── Step 12: Verify Supabase Storage artifacts ──────────────────────────
  console.log('\x1b[36m12. Verify Supabase Storage\x1b[0m');
  const { data: storageFiles } = await sb.storage
    .from('job-artifacts')
    .list(designId);
  const storageNames = (storageFiles || []).map(f => f.name);
  assert(storageNames.length > 5, `Storage has ${storageNames.length} files`);
  for (const key of ['placement_preview.svg', 'board.kicad_sch', 'board.kicad_pcb', 'resolved.json']) {
    assert(storageNames.includes(key), `Storage has ${key}`);
  }

  // ── Step 13: Approve engineer review ────────────────────────────────────
  console.log('\x1b[36m13. Approve engineer review\x1b[0m');
  const approve = await api('POST', '/api/internal/approve-review', { designId }, {
    'x-service-key': SB_KEY,
  });
  assert(approve.ok, 'Engineer review approved', approve.json?.error);

  // ── Step 14: Wait for awaiting_placement_approval ───────────────────────
  console.log('\x1b[36m14. Wait for placement approval stage\x1b[0m');
  const reachedPlacement = await poll(async () => {
    const s = await getDesignStatus(designId);
    process.stdout.write(`    status: ${s}          \r`);
    return s === 'awaiting_placement_approval' || s === 'failed' ? s : null;
  }, 30_000, 1_000);
  console.log('');
  assert(reachedPlacement === 'awaiting_placement_approval',
    `Reached awaiting_placement_approval (got: ${reachedPlacement})`);

  // ── Step 15: Approve placement (customer approval) ──────────────────────
  console.log('\x1b[36m15. Approve placement\x1b[0m');
  const approvePlace = await api('POST', `/api/jobs/${designId}/approve-placement`, {}, authHeader);
  assert(approvePlace.ok, 'Placement approved', approvePlace.json?.error);

  // ── Step 16: Wait for pipeline completion → files_ready ─────────────────
  console.log('\x1b[36m16. Wait for routing → packaging → files_ready\x1b[0m');
  const finalStatus = await poll(async () => {
    const s = await getDesignStatus(designId);
    process.stdout.write(`    status: ${s}          \r`);
    return ['files_ready', 'complete', 'failed'].includes(s) ? s : null;
  }, 300_000, 3_000);
  console.log('');
  assert(finalStatus === 'files_ready' || finalStatus === 'complete',
    `Pipeline completed (status: ${finalStatus})`);

  if (finalStatus === 'failed') {
    console.log('\n\x1b[31mPipeline failed after placement approval. Check worker logs.\x1b[0m');
  }

  // ── Step 17: Verify final artifacts ─────────────────────────────────────
  if (finalStatus === 'files_ready' || finalStatus === 'complete') {
    console.log('\x1b[36m17. Verify final artifacts\x1b[0m');
    const finalFiles = ['board.dsn', 'board.ses', 'drc_report.json', 'output.zip'];
    for (const f of finalFiles) {
      const fp = path.join(jobDir, f);
      const exists = fs.existsSync(fp);
      const size = exists ? fs.statSync(fp).size : 0;
      assert(exists && size > 0, `${f} exists (${size} bytes)`, exists ? '' : 'MISSING');
    }
  }

  // ── Results ─────────────────────────────────────────────────────────────
  printResults();
  process.exit(failed > 0 ? 1 : 0);
}

function printResults() {
  console.log(`\n\x1b[1m═══ Results ═══\x1b[0m`);
  console.log(`  \x1b[32m${passed} passed\x1b[0m`);
  if (failed > 0) console.log(`  \x1b[31m${failed} failed\x1b[0m`);
  else console.log('  \x1b[32mAll tests passed!\x1b[0m');
  console.log('');
}

main().catch(err => {
  console.error('\n\x1b[31mUnexpected error:\x1b[0m', err.message);
  printResults();
  process.exit(1);
});
