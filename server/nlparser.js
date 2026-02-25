'use strict';

const Anthropic = require('@anthropic-ai/sdk');
const path      = require('path');
const fs        = require('fs');

// Load capability taxonomy once at module load time
const capData   = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'data', 'capabilities.json'), 'utf8')
);
const CAPS_LIST = capData.capabilities;        // [{ id, display_label, group, ... }]
const VALID_IDS = new Set(CAPS_LIST.map(c => c.id));
const CAP_ID_LIST = CAPS_LIST.map(c => c.id);

// ─── System prompt ────────────────────────────────────────────────────────────

function buildSystemPrompt() {
  return `You are a PCB requirements parser for a circuit board design tool.
Given a plain English project description, return ONLY a valid JSON object.
No explanation, no markdown fences, no preamble — raw JSON only.

Available capability IDs (use ONLY these exact strings):
${JSON.stringify(CAP_ID_LIST)}

Return this exact schema:
{
  "capabilities": ["capability_id_1", "capability_id_2"],
  "suggested_board": {
    "layers": 2,
    "dimensions_mm": [80, 60],
    "power_source": "power_usb"
  },
  "confidence_notes": [
    "Assumed USB power — change if battery needed"
  ]
}

Rules:
- Only include capabilities that are clearly needed or strongly implied
- If processing power is not mentioned, default to processing_standard
- If power source is ambiguous, pick the most likely and note it in confidence_notes
- "sends data to phone" → bluetooth or wifi (pick based on context; wifi if mentions app/server)
- "runs for weeks/months/years" or "long battery life" → low_power_sleep
- "soil moisture" or "water level" → sense_adc_external (no dedicated cap exists)
- dimensions_mm: estimate based on component count and type, keep realistic (50×50 to 150×100 mm)
- layers: 2 unless RF + sensors + motor drivers together suggest 4
- power_source field must be one of the capability IDs above (e.g. power_usb, power_lipo, power_mains, power_solar)`;
}

// ─── Core parser ──────────────────────────────────────────────────────────────

/**
 * parseIntent(description)
 *
 * Calls Claude API to convert a plain-English project description into a
 * structured capability selection + board suggestion.
 *
 * @param {string} description - User's plain-English project description
 * @returns {Promise<{ success: boolean, result?: object, error?: string, raw?: string }>}
 */
async function parseIntent(description) {
  if (!process.env.ANTHROPIC_API_KEY) {
    return { success: false, error: 'ANTHROPIC_API_KEY not configured' };
  }

  const client = new Anthropic();

  let raw;
  try {
    const response = await client.messages.create({
      model:      'claude-sonnet-4-6',
      max_tokens: 1024,
      system:     buildSystemPrompt(),
      messages:   [{ role: 'user', content: description }],
    });

    raw = response.content[0].text.trim();

    // Strip accidental markdown fences if model slips
    if (raw.startsWith('```')) {
      raw = raw.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim();
    }
  } catch (apiErr) {
    console.error('[nlparser] Anthropic API error:', apiErr.message);
    return { success: false, error: 'Claude API call failed', detail: apiErr.message };
  }

  // ── Parse + validate ──────────────────────────────────────────────────────
  try {
    const parsed = JSON.parse(raw);

    // Filter out any hallucinated capability IDs
    const original = parsed.capabilities || [];
    parsed.capabilities = original.filter(id => VALID_IDS.has(id));

    // Warn in notes if IDs were dropped
    const dropped = original.filter(id => !VALID_IDS.has(id));
    if (dropped.length > 0) {
      parsed.confidence_notes = parsed.confidence_notes || [];
      parsed.confidence_notes.push(`Note: unrecognised capabilities ignored: ${dropped.join(', ')}`);
    }

    // Ensure suggested_board has sensible defaults
    parsed.suggested_board = {
      layers:        2,
      dimensions_mm: [80, 60],
      power_source:  'power_usb',
      ...(parsed.suggested_board || {}),
    };

    parsed.confidence_notes = parsed.confidence_notes || [];

    return { success: true, result: parsed };
  } catch (parseErr) {
    console.error('[nlparser] JSON parse failed. Raw:', raw);
    return { success: false, error: 'Response was not valid JSON', raw };
  }
}

module.exports = { parseIntent };
