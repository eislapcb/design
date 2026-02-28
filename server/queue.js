'use strict';

/**
 * Eisla — BullMQ job queue (server/queue.js)
 *
 * Wraps BullMQ Queue with:
 *   - Graceful Redis unavailability (warns but doesn't crash)
 *   - Safe enqueue() that returns null instead of throwing if Redis is down
 *   - Deduplication support (jobId option on delayed jobs)
 *
 * Requires Redis running at REDIS_URL (default: redis://localhost:6379).
 * Without Redis the API still serves requests; jobs simply won't process.
 */

const { Queue } = require('bullmq');
const IORedis    = require('ioredis');

const QUEUE_NAME = 'eisla-jobs';

let _connection = null;
let _queue      = null;
let _redisReady = false;

// ─── Redis connection ─────────────────────────────────────────────────────────

function getConnection() {
  if (!_connection) {
    _connection = new IORedis(process.env.REDIS_URL || 'redis://localhost:6379', {
      maxRetriesPerRequest: null,   // required by BullMQ
      enableReadyCheck:     false,
      lazyConnect:          true,
    });

    _connection.on('ready', () => {
      _redisReady = true;
      console.log('[queue] Redis connected');
    });

    _connection.on('error', err => {
      if (_redisReady) {
        console.warn('[queue] Redis error:', err.message);
      } else if (err.code === 'ECONNREFUSED') {
        // Only log once — not on every retry
        if (!_connection._warnedOffline) {
          console.warn('[queue] Redis not available — job processing disabled. Start Redis to enable.');
          _connection._warnedOffline = true;
        }
      }
    });
  }
  return _connection;
}

// ─── Queue ────────────────────────────────────────────────────────────────────

function getQueue() {
  if (!_queue) {
    _queue = new Queue(QUEUE_NAME, {
      connection: getConnection(),
      defaultJobOptions: {
        attempts: 3,
        backoff: { type: 'exponential', delay: 5_000 },
        removeOnComplete: 100,
        removeOnFail:     200,
      },
    });
  }
  return _queue;
}

/**
 * enqueue(name, data, opts)
 *
 * Safely adds a job. Returns the BullMQ Job on success, null on Redis failure.
 * Callers must handle null — the design still gets created in Supabase
 * even when the queue is unavailable.
 */
async function enqueue(name, data, opts = {}) {
  try {
    return await getQueue().add(name, data, opts);
  } catch (err) {
    console.error(`[queue] Failed to enqueue ${name}:`, err.message);
    return null;
  }
}

/**
 * removeJob(jobId)
 *
 * Removes a delayed job (e.g. auto-approve-{designId}) by its deduplication key.
 * Silently ignores errors (job may have already fired or never been created).
 */
async function removeJob(jobId) {
  try {
    const job = await getQueue().getJob(jobId);
    if (job) await job.remove();
  } catch {
    // silently ignore
  }
}

module.exports = { getQueue, getConnection, enqueue, removeJob, QUEUE_NAME };
