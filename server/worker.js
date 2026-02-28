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
const notifier        = require('./notifier');

const execFileAsync = promisify(execFile);

// ─── Config ───────────────────────────────────────────────────────────────────

const JOBS_DIR  = path.resolve(process.env.JOBS_DIR  || './jobs');
// KiCad Python for pcbnew API (Stages 3b/3c, 11). Falls back to system Python for other scripts.
const PYTHON       = process.env.PYTHON      || 'python';
const KICAD_PYTHON = process.env.KICAD_PYTHON || 'C:/Program Files/KiCad/9.0/bin/python.exe';
const JAVA         = process.env.JAVA_BIN     || 'java';
const PY_DIR    = path.join(__dirname, '..', 'python');
const FR_JAR    = path.resolve(process.env.FREEROUTING_JAR || './freerouting/freerouting.jar');
const PLACEMENT_TIMEOUT_H = parseInt(process.env.PLACEMENT_APPROVAL_TIMEOUT_HOURS || '24', 10);
const FREEROUTING_TIMEOUT_MS = parseInt(process.env.FREEROUTING_TIMEOUT_MS || String(90_000), 10);

// Lazy-load supabaseAdmin to avoid circular import issues
let _supa;
function supa() {
  if (!_supa) _supa = require('./accounts').supabaseAdmin || require('./accounts');
  return _supa;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function supaAdmin() {
  const { createClient } = require('@supabase/supabase-js');
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
  );
}

async function updateStatus(designId, status) {
  const { error } = await supaAdmin().from('designs').update({ status }).eq('id', designId);
  if (error) console.error(`[worker] Status update failed for ${designId}:`, error.message);
  else console.log(`[worker] ${designId} → ${status}`);
}

async function updateDesignField(designId, fields) {
  const { error } = await supaAdmin().from('designs').update(fields).eq('id', designId);
  if (error) console.error(`[worker] Design update failed for ${designId}:`, error.message);
}

async function getDesign(designId) {
  const { data, error } = await supaAdmin().from('designs').select('*').eq('id', designId).single();
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
async function runPython(script, args = [], timeoutMs = 60_000, { kicad = false } = {}) {
  const scriptPath = path.join(PY_DIR, script);
  const interpreter = kicad ? KICAD_PYTHON : PYTHON;
  try {
    const result = await execFileAsync(interpreter, [scriptPath, ...args], {
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

  const boardJson = {
    ...boardCfg,
    dimensions_mm: boardCfg.dimensions_mm || [100, 80],
    layers:        boardCfg.layers        || resolved.recommended_layers || 2,
    power_source:  boardCfg.power_source  || 'usb',
    description:   design.description     || '',
  };

  // Write input files to disk
  writeJobFile(designId, 'resolved.json', resolved);
  writeJobFile(designId, 'board.json', boardJson);

  // Gap 1 fix: write resolved data back to Supabase so ops hub can read it
  await updateDesignField(designId, { resolved });

  return { resolved, design };
}

// ─── Stage 2 — Validation ─────────────────────────────────────────────────────

async function stageValidate(designId) {
  await runPython('validator.py', [jobDir(designId)]);
}

// ─── Stage 3 — Placement ──────────────────────────────────────────────────────

async function stagePlacement(designId) {
  await runPython('placement.py', [jobDir(designId)], 30_000); // 30s timeout
}

// ─── Stage 3b — Netlist generation ────────────────────────────────────────────

async function stageNetlist(designId) {
  await runPython('netlist.py', [jobDir(designId)]);
}

// ─── Stage 3c — KiCad PCB file (requires KiCad Python / pcbnew) ──────────────

async function stageKicadPcb(designId) {
  await runPython('kicad_pcb.py', [jobDir(designId)], 60_000, { kicad: true });
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
    const { design } = await stageIntake(designId);
    const tier = design.tier || 1;

    // Stage 2 — Validate
    await updateStatus(designId, 'validating');
    await stageValidate(designId);

    // Stage 3 — Placement
    await updateStatus(designId, 'placing');
    await stagePlacement(designId);

    // Stage 3b — Netlist
    await stageNetlist(designId);

    // Stage 3c — KiCad PCB file (pcbnew API)
    await stageKicadPcb(designId);

    // Stage 4 — SVG preview
    await stageSvgPreview(designId);

    // Gap 3 fix: upload key artifacts to Supabase Storage for ops hub access
    await uploadJobArtifacts(designId);

    // Gap 2 fix: T2/T3 require engineer review before customer sees placement
    if (tier >= 2) {
      await updateStatus(designId, 'awaiting_engineer_review');
      console.log(`[worker] Design ${designId} (T${tier}) awaiting engineer review`);
      // Pipeline pauses here. Ops hub engineer calls POST /api/internal/approve-review
      // which enqueues 'engineer-reviewed' to advance to customer approval.
      return;
    }

    // T1: skip engineer review — go straight to customer approval
    await updateStatus(designId, 'awaiting_placement_approval');

    // Schedule auto-approve
    await enqueue('auto-approve-placement', { designId }, {
      delay: PLACEMENT_TIMEOUT_H * 3_600_000,
      jobId: `auto-approve-${designId}`,
    });

    // Best-effort email — never fails the pipeline
    notifier.notifyCustomer(designId, 'placement_ready').catch(() => {});

    console.log(`[worker] Design ${designId} (T1) awaiting placement approval`);

  } catch (err) {
    console.error(`[worker] Design ${designId} failed:`, err.message);
    await updateStatus(designId, 'failed');
    throw err;
  }
}

// ─── Gap 3: Upload job artifacts to Supabase Storage ──────────────────────────

async function uploadJobArtifacts(designId) {
  const admin = supaAdmin();
  const dir   = jobDir(designId);
  const bucket = 'job-artifacts';

  // Files to upload for ops hub / customer access
  const artifacts = [
    'placement_preview.svg',
    'placement.json',
    'validation_warnings.json',
    'engineer_review_flags.json',
    'resolved.json',
    'board.json',
  ];

  for (const name of artifacts) {
    const filePath = path.join(dir, name);
    if (!fs.existsSync(filePath)) continue;

    const content = fs.readFileSync(filePath);
    const storagePath = `${designId}/${name}`;
    const contentType = name.endsWith('.svg') ? 'image/svg+xml' : 'application/json';

    const { error } = await admin.storage
      .from(bucket)
      .upload(storagePath, content, { contentType, upsert: true });

    if (error) {
      // Non-fatal — log and continue. Storage bucket may not exist yet.
      console.warn(`[worker] Upload ${name} failed: ${error.message}`);
    }
  }

  console.log(`[worker] Artifacts uploaded for ${designId}`);
}

async function uploadOutputZip(designId) {
  const admin = supaAdmin();
  const zipPath = path.join(jobDir(designId), 'output.zip');
  if (!fs.existsSync(zipPath)) return;

  const content = fs.readFileSync(zipPath);
  const { error } = await admin.storage
    .from('job-artifacts')
    .upload(`${designId}/output.zip`, content, {
      contentType: 'application/zip',
      upsert: true,
    });

  if (error) console.warn(`[worker] Upload output.zip failed: ${error.message}`);
  else console.log(`[worker] output.zip uploaded for ${designId}`);
}

// ─── Engineer review completion (T2/T3 only) ─────────────────────────────────

async function engineerReviewed(job) {
  const { designId } = job.data;
  console.log(`[worker] Engineer review complete for ${designId} — advancing to customer approval`);

  await updateStatus(designId, 'awaiting_placement_approval');

  // Schedule auto-approve
  await enqueue('auto-approve-placement', { designId }, {
    delay: PLACEMENT_TIMEOUT_H * 3_600_000,
    jobId: `auto-approve-${designId}`,
  });

  // Best-effort email — never fails the pipeline
  notifier.notifyCustomer(designId, 'placement_ready').catch(() => {});
}

// ─── Stage 11a — DSN export ───────────────────────────────────────────────────

async function stageDsnExport(designId) {
  await runPython('dsn_export.py', [jobDir(designId)], 30_000, { kicad: true });
}

// ─── Stage 11b — FreeRouting (Java subprocess) ────────────────────────────────

async function stageFreeRouting(designId) {
  const dir = jobDir(designId);
  const dsn = path.join(dir, 'board.dsn');
  const ses = path.join(dir, 'board.ses');

  if (!fs.existsSync(FR_JAR)) {
    throw new Error(`freerouting.jar not found at ${FR_JAR}`);
  }
  if (!fs.existsSync(dsn)) {
    throw new Error(`board.dsn not found in ${dir}`);
  }

  console.log(`[worker] Running FreeRouting for ${designId} ...`);

  await execFileAsync(JAVA, [
    '-jar', FR_JAR,
    '-de', dsn,
    '-do', ses,
  ], { timeout: FREEROUTING_TIMEOUT_MS });

  if (!fs.existsSync(ses)) {
    throw new Error('FreeRouting did not produce board.ses');
  }

  const sizeKb = Math.round(fs.statSync(ses).size / 1024);
  console.log(`[worker] FreeRouting complete: board.ses ${sizeKb} KB`);
}

// ─── Stage 11c — DRC (imports .ses, runs DRC, writes drc_report.json) ─────────

async function stageDrc(designId) {
  // drc.py exits 1 on violations — catch so we can store status without crashing pipeline
  try {
    await runPython('drc.py', [jobDir(designId)], 60_000, { kicad: true });
  } catch (err) {
    // If exit code is non-zero, DRC found errors — store in job file and continue
    console.warn(`[worker] DRC found violations for ${designId}: ${err.message}`);
    const drcReport = readJobFile(designId, 'drc_report.json');
    if (drcReport && (drcReport.error_count > 0 || drcReport.unrouted_count > 0)) {
      // Non-fatal — customer will see DRC warnings in the download
      return;
    }
    throw err;
  }
}

// ─── Placement approval ───────────────────────────────────────────────────────

async function approvePlacement(job) {
  const { designId } = job.data;
  console.log(`[worker] Approving placement for ${designId}`);

  // Cancel auto-approve (if customer approved manually before timeout)
  await removeJob(`auto-approve-${designId}`);

  try {
    // Stage 11a — DSN export
    await updateStatus(designId, 'routing');
    await stageDsnExport(designId);

    // Stage 11b — FreeRouting
    await stageFreeRouting(designId);

    // Stage 11c — Import .ses + DRC
    await stageDrc(designId);

    // Schematic generation (post-routing)
    try {
      await runPython('schematic.py', [jobDir(designId)]);
    } catch (err) {
      console.warn(`[worker] Schematic generation failed (non-fatal): ${err.message}`);
    }

    // Stage 12 — Post-processing (Gerbers, BOM, P&P, ZIP)
    await updateStatus(designId, 'packaging');
    await runPython('postprocess.py', [jobDir(designId)], 120_000, { kicad: true });

    // Upload output.zip to Supabase Storage
    await uploadOutputZip(designId);

    // Advance to files_ready
    await updateStatus(designId, 'files_ready');
    // Best-effort email — never fails the pipeline
    notifier.notifyCustomer(designId, 'files_ready').catch(() => {});
    // TODO (Session 16): fabquoter.js → status 'quoting' → 'complete'
    console.log(`[worker] Design ${designId} files ready for download`);

  } catch (err) {
    console.error(`[worker] Routing failed for ${designId}:`, err.message);
    await updateStatus(designId, 'failed');
    throw err;
  }
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
      case 'engineer-reviewed':
        return engineerReviewed(job);
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
