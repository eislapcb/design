"""
Eisla -- Placement Profile Harvester (python/placement_harvest.py)

Post-pipeline step. Extracts a compact placement profile from a successful
(DRC-clean) job and appends it to data/placement_profiles.json.
Also updates weight statistics in data/placement_weights.json and
incrementally tunes SA weights based on accumulated outcomes.

Usage:
    python placement_harvest.py <job_dir>

Input files (in job_dir):
    placement.json          -- component positions, score
    board.json              -- board dimensions, layer count
    placement_warnings.json -- post-placement quality warnings
    drc_report.json         -- DRC results (must be clean)

Output (project-level):
    data/placement_profiles.json  -- appended with new profile
    data/placement_weights.json   -- updated statistics + tuned weights
"""

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR     = PROJECT_ROOT / "data"
PROFILES_PATH = DATA_DIR / "placement_profiles.json"
WEIGHTS_PATH  = DATA_DIR / "placement_weights.json"

MAX_PROFILES = 250
MAX_WEIGHT_HISTORY = 20

DEFAULT_WEIGHTS = {
    "overlap": 200.0,
    "overlap_floor": 100.0,
    "zone_priority_scale": 0.3,
    "boundary": 100.0,
    "antenna_keepout": 200.0,
    "proximity": 5.0,
    "crystal": 50.0,
    "crystal_threshold_mm": 5.0,
    "decoupling": 30.0,
    "block_cohesion_passive": 0.3,
    "block_cohesion_active": 1.5,
    "block_separation_min_mm": 15.0,
    "block_separation_penalty": 2.0,
}


# ─── File I/O ────────────────────────────────────────────────────────────────

def _load_json(path):
    path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _atomic_write(path, data):
    """Write JSON atomically via temp file + rename."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_profiles():
    try:
        return _load_json(PROFILES_PATH) or []
    except (json.JSONDecodeError, IOError):
        return []


def save_profiles(profiles):
    _atomic_write(PROFILES_PATH, profiles)


def load_weights():
    try:
        data = _load_json(WEIGHTS_PATH)
        if data and "defaults" in data and "learned" in data:
            return data
    except (json.JSONDecodeError, IOError):
        pass
    return {
        "defaults": dict(DEFAULT_WEIGHTS),
        "learned": dict(DEFAULT_WEIGHTS),
        "stats": {"total_profiles": 0, "clean_profiles": 0, "weight_history": []},
    }


def save_weights(weights_data):
    _atomic_write(WEIGHTS_PATH, weights_data)


# ─── Profile building ────────────────────────────────────────────────────────

def build_profile(job_dir):
    """Build a compact placement profile from job artifacts."""
    job_dir = Path(job_dir)

    placement = _load_json(job_dir / "placement.json")
    board_cfg = _load_json(job_dir / "board.json") or {}
    warnings  = _load_json(job_dir / "placement_warnings.json") or {}
    drc       = _load_json(job_dir / "drc_report.json") or {}

    if not placement:
        return None

    board = placement.get("board", {})
    w = board.get("w_mm", 100.0)
    h = board.get("h_mm", 80.0)
    layers = board_cfg.get("layers", 4)

    components = placement.get("components", [])
    component_ids = sorted(set(c["component_id"] for c in components))

    # Build relative positions per component_id
    positions = {}
    zones = {}
    for comp in components:
        cid = comp["component_id"]
        entry = {
            "rx": round(comp["x_mm"] / w, 4) if w > 0 else 0,
            "ry": round(comp["y_mm"] / h, 4) if h > 0 else 0,
            "rot": comp.get("rotation_deg", 0),
        }
        if cid in positions:
            existing = positions[cid]
            if isinstance(existing, dict):
                positions[cid] = [existing, entry]
            else:
                existing.append(entry)
        else:
            positions[cid] = entry

        zones[cid] = comp.get("placement_zone", "any")

    score_data = placement.get("score", {})
    weights_used = placement.get("weights_used", dict(DEFAULT_WEIGHTS))

    # Build compact ID from fingerprint + timestamp
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fp_str = f"{w}x{h}:{layers}:{','.join(component_ids)}:{ts}"
    profile_id = hashlib.sha256(fp_str.encode()).hexdigest()[:8]

    return {
        "id": profile_id,
        "timestamp": ts,
        "fingerprint": {
            "board_w_mm": w,
            "board_h_mm": h,
            "layers": layers,
            "component_ids": component_ids,
        },
        "positions": positions,
        "zones": zones,
        "outcome": {
            "sa_improvement_pct": round(score_data.get("improvement_pct", 0), 1),
            "placement_warning_count": warnings.get("warning_count", 0),
            "drc_clean": drc.get("clean", False),
        },
        "weights_used": weights_used,
    }


# ─── Weight tuning ───────────────────────────────────────────────────────────

def update_weight_stats(profile, weights_data):
    """Record this profile's outcome in weight statistics."""
    stats = weights_data.setdefault("stats", {
        "total_profiles": 0, "clean_profiles": 0, "weight_history": [],
    })
    stats["total_profiles"] = stats.get("total_profiles", 0) + 1
    if profile["outcome"]["drc_clean"]:
        stats["clean_profiles"] = stats.get("clean_profiles", 0) + 1

    # Append to weight history (ring buffer)
    history = stats.setdefault("weight_history", [])
    history.append({
        "weights": profile.get("weights_used", {}),
        "drc_clean": profile["outcome"]["drc_clean"],
        "sa_improvement_pct": profile["outcome"]["sa_improvement_pct"],
    })
    if len(history) > MAX_WEIGHT_HISTORY:
        stats["weight_history"] = history[-MAX_WEIGHT_HISTORY:]

    return weights_data


def tune_weights(weights_data):
    """Incrementally adjust learned weights based on accumulated outcomes.
    Only runs when total_profiles >= 10."""
    stats = weights_data.get("stats", {})
    total = stats.get("total_profiles", 0)
    history = stats.get("weight_history", [])

    if total < 10 or len(history) < 10:
        return weights_data

    defaults = weights_data.get("defaults", DEFAULT_WEIGHTS)
    learned = weights_data.get("learned", dict(DEFAULT_WEIGHTS))

    for key in DEFAULT_WEIGHTS:
        vals_clean = [
            e["weights"].get(key)
            for e in history
            if e.get("drc_clean") and e.get("weights", {}).get(key) is not None
        ]
        vals_dirty = [
            e["weights"].get(key)
            for e in history
            if not e.get("drc_clean") and e.get("weights", {}).get(key) is not None
        ]

        if not vals_clean:
            continue

        avg_clean = sum(vals_clean) / len(vals_clean)
        all_vals = vals_clean + vals_dirty
        avg_all = sum(all_vals) / len(all_vals)

        if abs(avg_clean - avg_all) < 0.001:
            continue

        current = learned.get(key, defaults.get(key, 1.0))
        direction = 1.0 if avg_clean > current else -1.0
        magnitude = min(abs(avg_clean - current) * 0.3, current * 0.10)
        new_val = current + direction * magnitude

        # Clamp to [default * 0.5, default * 2.0]
        default_val = defaults.get(key, 1.0)
        low = default_val * 0.5
        high = default_val * 2.0
        new_val = max(low, min(high, new_val))

        learned[key] = round(new_val, 4)

    weights_data["learned"] = learned
    return weights_data


# ─── Main ────────────────────────────────────────────────────────────────────

def harvest(job_dir):
    """Extract profile from a completed job and update learning data."""
    job_dir = Path(job_dir)

    # Gate: only harvest DRC-clean jobs
    drc = _load_json(job_dir / "drc_report.json")
    if not drc or not drc.get("clean", False):
        print("[harvest] Skipping: DRC not clean")
        return

    profile = build_profile(job_dir)
    if not profile:
        print("[harvest] Skipping: could not build profile")
        return

    # Append profile (dedup by id, enforce cap)
    profiles = load_profiles()
    existing_ids = {p["id"] for p in profiles}
    if profile["id"] not in existing_ids:
        profiles.append(profile)
        if len(profiles) > MAX_PROFILES:
            profiles = profiles[-MAX_PROFILES:]
        save_profiles(profiles)

    # Update weight stats + tune
    weights_data = load_weights()
    weights_data = update_weight_stats(profile, weights_data)
    weights_data = tune_weights(weights_data)
    save_weights(weights_data)

    print(f"[harvest] Profile {profile['id']} saved "
          f"({len(profile['fingerprint']['component_ids'])} components, "
          f"DRC clean={profile['outcome']['drc_clean']})")
    print(f"[harvest] {weights_data['stats']['total_profiles']} total profiles, "
          f"{weights_data['stats']['clean_profiles']} clean")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python placement_harvest.py <job_dir>")
        sys.exit(1)
    harvest(sys.argv[1])
