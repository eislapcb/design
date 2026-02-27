# Eisla

**From words to boards.**
Describe your project. We build the circuit board.

Eisla is an AI-powered PCB design and manufacturing service for non-engineers. Users describe what they want their board to do in plain English; Eisla handles component selection, board design, engineering validation, and order placement across multiple manufacturers — no electronics knowledge required.

---

## Quick Start

### 1. Clone & Open
```bash
git clone https://github.com/eislapcb/design.git
cd design
code .
```

### 2. Install Dependencies
Open the integrated terminal (`` Ctrl+` ``):
```bash
# Node.js dependencies (server)
npm install --ignore-scripts

# Python dependencies (Nexar validator)
python -m pip install requests
```

> **Note:** `better-sqlite3` requires Visual Studio C++ build tools (not yet needed — SQLite integration is a later session). The `--ignore-scripts` flag skips its compilation safely.

### 3. Configure Environment
```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY
```

### 4. Start the API Server
```bash
# Add Node to PATH if using Git Bash on Windows:
export PATH="/c/Program Files/nodejs:$PATH"

node server/index.js
# → Eisla API running on http://localhost:3001
```

### 5. Install Recommended Extensions
VS Code will prompt you to install recommended extensions on first open.
Click **"Install All"** — or manually install:
- **Live Server** (ritwickdey.LiveServer) — frontend preview
- **Python** (ms-python.python) — validation scripts
- **Prettier** (esbenp.prettier-vscode) — code formatting

---

## Project Structure

```
eisla/
│
├── .vscode/                    # VS Code config
│   ├── settings.json
│   └── extensions.json
│
├── data/                       # Core data layer
│   ├── components.json         # Component database (199+ parts, 8 categories)
│   ├── capabilities.json       # Capability taxonomy (50+ IDs)
│   ├── component_template.json # Schema template for adding new parts
│   ├── validation_rules.json   # Board-level validation rules
│   ├── rules/                  # Design rule engine
│   │   ├── connection_templates.json
│   │   ├── crystal_layout_rules.json
│   │   ├── i2c_conflict_rules.json
│   │   ├── mains_safety_rules.json
│   │   ├── mcu_pin_tables.json
│   │   ├── multi_mcu_rules.json
│   │   ├── net_naming_conventions.json
│   │   ├── power_budget_model.json
│   │   ├── protection_rules.json
│   │   ├── safety_disclaimer.json
│   │   ├── silkscreen_rules.json
│   │   └── thermal_rules.json
│   ├── examples/
│   │   ├── PIC32CK2051SG01064_component.json
│   │   └── weather_station.kicad_sch
│   └── fab_rates/              # Fab pricing rate cards (Session 3)
│
├── server/                     # Node.js API (port 3001 — ops hub is on 3000)
│   ├── index.js                # Express server — all API routes
│   ├── resolver.js             # 8-step capability → component resolver
│   ├── nlparser.js             # Claude API natural language parser
│   ├── validate.js             # Data validation script
│   └── check_component.js      # Single component checker
│
├── python/                     # Python tools
│   ├── validate_components.py  # Nexar API database validator
│   ├── run_validation.py       # Standalone validation runner
│   ├── test_component_addition.py
│   └── requirements.txt
│
├── frontend/                   # Web UI (Session 18)
│   └── assets/
│
├── freerouting/                # Auto-router integration (Session 11)
├── db/                         # SQLite database (Session 4)
├── jobs/                       # Job queue (Session 9+)
│
├── docs/
│   ├── ADDING_COMPONENTS.md
│   └── iot-capability-gap-analysis.md
│
├── BRIEF.md                    # Full project specification
├── package.json
├── .env.example
├── .gitignore
└── README.md
```

---

## API Endpoints (live)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Server status |
| `GET` | `/api/capabilities` | Full capability taxonomy |
| `GET` | `/api/components` | Component list (summary) |
| `GET` | `/api/components/:id` | Single component detail |
| `POST` | `/api/parse-intent` | Plain-English → capability selections (requires `ANTHROPIC_API_KEY`) |
| `POST` | `/api/resolve` | Capability selections → component list + pricing |

---

## Key Files

| File | Purpose |
|------|---------|
| `BRIEF.md` | Full project spec — read this first |
| `server/resolver.js` | Core matching logic — capabilities → components |
| `server/nlparser.js` | Claude API wrapper for NL input |
| `data/components.json` | Component database |
| `data/capabilities.json` | Capability taxonomy |
| `data/rules/*.json` | Design rules (thermal, safety, layout, etc.) |
| `python/run_validation.py` | Nexar MPN validator |
| `docs/ADDING_COMPONENTS.md` | How to add new components |

---

## Build Progress

| Session | What | Status |
|---------|------|--------|
| 1 | Capability taxonomy + component database | ✅ Done |
| 2 | Capability resolver + pricing | ✅ Done |
| 3 | Fab rate cards | ⬜ |
| 4 | User accounts (SQLite) | ⬜ |
| 5 | Natural language parser | ✅ Done |
| 6 | Design validator | ⬜ |
| 7 | Stripe integration | ⬜ |
| 8 | API skeleton | 🔄 In progress |
| 9–17 | PCB generation pipeline | ⬜ |
| 18 | Frontend | ⬜ |
| 19–20 | Accounts frontend + deployment | ⬜ |

**Target launch:** April 2026

---

## Environment Variables

| Variable | Required for |
|----------|-------------|
| `ANTHROPIC_API_KEY` | `/api/parse-intent` NL parsing |
| `STRIPE_SECRET_KEY` | Payment processing (Session 7) |
| `REDIS_URL` | Job queue (Session 9+) |
| `JLCPCB_APP_ID` / `_ACCESS_KEY` / `_SECRET_KEY` | Fab ordering (Session 15) |
| `SMTP_*` | Email notifications (Session 13) |
