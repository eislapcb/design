'use strict';

/**
 * Eisla — Job worker (server/worker.js)
 *
 * Runs as a separate process: node server/worker.js
 * Requires Redis + Supabase configured in .env.
 *
 * Pipeline (Sessions implemented per session number):
 *   Stage 1  — Job intake (write input files)             [S8]
 *   Stage 2  — Design validation (python/validator.py)    [S6/S8]
 *   Stage 3  — Placement (python/placement.py)            [S9]
 *   Stage 4  — SVG preview (python/svg_preview.py)        [S9]
 *              → status: awaiting_placement_approval
 *   Stage 5  — Placement approval (customer or auto)      [S8]
 *   Stage 6  — Routing (FreeRouting)                      [S11 stub]
 *   Stage 7  — DRC (KiCad pcbnew)                         [S11 stub]
 *   Stage 8  — Schematic generation (python/schematic.py) [S12 stub]
 *   Stage 9  — Post-processing / Gerbers / ZIP            [S12 stub]
 *   Stage 10 — Fab quoting (server/fabquoter.js)          [S16 stub]
 */

require('dotenv').config();

const { Worker }     = require('bullmq');
const { execFile }   = require('child_process');
const { promisify }  = require('util');
const fs             = require('fs');
const path           = require('path');

const { getConnection, QUEUE_NAME, enqueue, removeJob } = require('./queue');
const { getProfile }  = require('./accounts');
const { resolve }     = require('./resolver');

const execFileAsync = promisify(execFile);

// ─── Config ───────────────────────────────────────────────────────────────────

const JOBS_DIR  = path.resolve(process.env.JOBS_DIR  || './jobs');
const PYTHON    = process.env.KICAD_PYTHON            || 'python';
const PY_DIR    = path.join(__dirname, '..', 'python');
const PLACEMENT_TIMEOUT_H = parseInt(process.env.PLACEMENT_APPROVAL_TIMEOUT_HOURS || '24', 10);

// Lazy-load supabaseAdmin to avoid circular import issues
let _supa;
function supa() {
  if (!_supa) _supa = require('./accounts').supabaseAdmin || require('./accounts');
  return _supa;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function updateStatus(designId, status) {
  const { createClient } = require('@supabase/supabase-js');
  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
  );
  const { error } = await admin.from('designs').update({ status }).eq('id', designId);
  if (error) console.error(`[worker] Status update failed for ${designId}:`, error.message);
  else console.log(`[worker] ${designId} → ${status}`);
}

async function getDesign(designId) {
  const { createClient } = require('@supabase/supabase-js');
  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
  );
  const { data, error } = await admin.from('designs').select('*').eq('id', designId).single();
  if (error) throw new Error(`Design not found: ${error.message}`);
  return data;
}

function jobDir(designId) {
  return path.join(JOBS_DIR, designId);
}

function writeJobFile(designId, filename, content) {
  const dir = jobDir(designId);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, filename),
    typeof content === 'string' ? content : JSON.stringify(content, null, 2),
    'utf8'
  );
}

function readJobFile(designId, filename) {
  const p = path.join(jobDir(designId), filename);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

/**
 * Run a Python script in the job directory.
 * Returns { stdout, stderr }.
 */
async function runPython(script, args = [], timeoutMs = 60_000) {
  const scriptPath = path.join(PY_DIR, script);
  try {
    const result = await execFileAsync(PYTHON, [scriptPath, ...args], {
      timeout: timeoutMs,
      cwd: path.resolve('.'),
    });
    if (result.stderr) console.warn(`[${script}] stderr:`, result.stderr.slice(0, 500));
    return result;
  } catch (err) {
    throw new Error(`Python ${script} failed: ${err.message}`);
  }
}

// ─── Stage 1 — Job intake ─────────────────────────────────────────────────────

async function stageIntake(designId) {
  const design = await getDesign(designId);
  const caps   = Array.isArray(design.capabilities) ? design.capabilities : [];
  const boardCfg = design.resolved?.board_config || {};

  // Re-run resolver to get full resolved output
  const resolved = resolve({
    capabilities:    caps,
    board:           boardCfg,
    repeat_customer: false,
  });

  // Write input files
  writeJobFile(designId, 'resolved.json', resolved);
  writeJobFile(designId, 'board.json', {
    ...boardCfg,
    dimensions_mm: boardCfg.dimensions_mm || [100, 80],
    layers:        boardCfg.layers        || resolved.recommended_layers || 2,
    power_source:  boardCfg.power_source  || 'usb',
    description:   design.description     || '',
  });

  return resolved;
}

// ─── Stage 2 — Validation ─────────────────────────────────────────────────────

async function stageValidate(designId) {
  await runPython('validator.py', [jobDir(designId)]);
}

// ─── Stage 3 — Placement ──────────────────────────────────────────────────────

async function stagePlacement(designId) {
  await runPython('placement.py', [jobDir(designId)], 30_000); // 30s timeout
}

// ─── Stage 4 — SVG preview ────────────────────────────────────────────────────

async function stageSvgPreview(designId) {
  await runPython('svg_preview.py', [jobDir(designId)]);
}

// ─── Main job processor ───────────────────────────────────────────────────────

async function processDesign(job) {
  const { designId } = job.data;
  console.log(`[worker] Processing design ${designId}`);

  try {
    // Stage 1 — Intake
    await stageIntake(designId);

    // Stage 2 — Validate
    await updateStatus(designId, 'validating');
    await stageValidate(designId);

    // Stage 3 — Placement
    await updateStatus(designId, 'placing');
    await stagePlacement(designId);

    // Stage 4 — SVG preview
    await stageSvgPreview(designId);

    // Done with automated stages — hand off to customer for approval
    await updateStatus(designId, 'awaiting_placement_approval');

    // Schedule auto-approve
    await enqueue('auto-approve-placement', { designId }, {
      delay: PLACEMENT_TIMEOUT_H * 3_600_000,
      jobId: `auto-approve-${designId}`,
    });

    // TODO (Session 13): notifier.sendPlacementReadyEmail(designId)

    console.log(`[worker] Design ${designId} awaiting placement approval`);

  } catch (err) {
    console.error(`[worker] Design ${designId} failed:`, err.message);
    await updateStatus(designId, 'failed');
    throw err;
  }
}

// ─── Placement approval ───────────────────────────────────────────────────────

async function approvePlacement(job) {
  const { designId } = job.data;
  console.log(`[worker] Approving placement for ${designId}`);

  // Cancel auto-approve (if customer approved manually before timeout)
  await removeJob(`auto-approve-${designId}`);

  await updateStatus(designId, 'routing');

  // TODO (Session 11): Run FreeRouting
  // await runFreeRouting(designId);
  console.log(`[worker] Routing stub — FreeRouting integration in Session 11`);

  // For now: mark as failed (placeholder — remove in Session 11)
  // In Session 11 this will advance to 'generating_schematic' → 'packaging' → 'files_ready' → 'quoting' → 'complete'
  await updateStatus(designId, 'failed');
}

// ─── Adjust placement (re-render SVG with overrides) ─────────────────────────

async function adjustPlacement(job) {
  const { designId, adjustments } = job.data;
  console.log(`[worker] Adjusting placement for ${designId}`);

  // Write overrides file
  writeJobFile(designId, 'placement_overrides.json', adjustments);

  // Re-run SVG preview with overrides flag
  await runPython('svg_preview.py', [jobDir(designId), '--overrides']);

  await updateStatus(designId, 'awaiting_placement_approval');
}

// ─── Start worker ─────────────────────────────────────────────────────────────

function startWorker() {
  console.log('[worker] Starting Eisla job worker...');

  const worker = new Worker(QUEUE_NAME, async job => {
    switch (job.name) {
      case 'process_design':
        return processDesign(job);
      case 'approve-placement':
      case 'auto-approve-placement':
        return approvePlacement(job);
      case 'adjust-placement':
        return adjustPlacement(job);
      default:
        console.warn(`[worker] Unknown job name: ${job.name}`);
    }
  }, {
    connection:  getConnection(),
    concurrency: parseInt(process.env.MAX_CONCURRENT_JOBS || '2', 10),
  });

  worker.on('completed', job => {
    console.log(`[worker] Job ${job.id} (${job.name}) completed`);
  });

  worker.on('failed', (job, err) => {
    console.error(`[worker] Job ${job?.id} (${job?.name}) failed: ${err.message}`);
  });

  worker.on('error', err => {
    console.error('[worker] Worker error:', err.message);
  });

  return worker;
}

// ─── Entry point ──────────────────────────────────────────────────────────────

if (require.main === module) {
  startWorker();
  console.log('[worker] Ready — waiting for jobs');
}

module.exports = { startWorker, jobDir, readJobFile, writeJobFile };
