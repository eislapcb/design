# Eisla — VS Code Project

AI-powered service that converts plain-English product descriptions into manufactured circuit boards for non-engineers.

## Quick Start

### 1. Extract & Open
```bash
unzip eisla-vscode.zip
cd eisla-vscode
code .
```
Or: **File → Open Folder** → select `eisla-vscode`

### 2. Install Dependencies
Open the integrated terminal (`` Ctrl+` ``):
```bash
# Node.js dependencies (for server & validation tools)
npm install

# Python dependencies (for Nexar API validator)
pip install requests
```

### 3. Install Recommended Extensions
VS Code will prompt you to install recommended extensions on first open.
Click **"Install All"** — or manually install:
- **Live Server** (ritwickdey.LiveServer) — for frontend preview
- **Python** (ms-python.python) — for validation scripts
- **Prettier** (esbenp.prettier-vscode) — code formatting

---

## Project Structure

```
eisla-vscode/
│
├── .vscode/                    # VS Code config
│   ├── settings.json           # Editor settings & JSON schema mapping
│   └── extensions.json         # Recommended extensions
│
├── data/                       # Core data layer
│   ├── components.json         # Component database (467KB, 24+ parts)
│   ├── capabilities.json       # System capabilities & feature flags
│   ├── component_template.json # Schema template for adding new parts
│   ├── validation_rules.json   # Board-level validation rules
│   ├── rules/                  # Design rule engine files
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
│   ├── examples/               # Reference files
│   │   ├── PIC32CK2051SG01064_component.json
│   │   └── weather_station.kicad_sch
│   └── fab_rates/              # JLCPCB/fab pricing (future)
│
├── server/                     # Node.js backend
│   ├── validate.js             # Component data validation
│   └── check_component.js      # Single component checker
│
├── python/                     # Python tools
│   ├── validate_components.py  # Nexar API database validator
│   ├── test_component_addition.py # Component addition tests
│   └── requirements.txt        # Python dependencies
│
├── frontend/                   # Web UI (future)
│   └── assets/
│
├── freerouting/                # Auto-router integration (future)
├── db/                         # Database files (future)
├── jobs/                       # Job queue (future)
│
├── docs/                       # Documentation
│   ├── ADDING_COMPONENTS.md    # How to add new components
│   └── iot-capability-gap-analysis.md
│
├── BRIEF.md                    # Full project specification (147KB)
├── package.json                # Node.js project config
├── .env.example                # Environment variable template
├── .gitignore                  # Git ignore rules
└── README.md                   # This file
```

---

## Key Files to Start With

| File | What It Does |
|------|-------------|
| `BRIEF.md` | Full project spec — read this first |
| `data/components.json` | The component database (the heart of the system) |
| `data/capabilities.json` | What the system can do |
| `data/rules/*.json` | All design rules (thermal, safety, layout, etc.) |
| `python/validate_components.py` | Validates DB against live Nexar/Octopart data |
| `docs/ADDING_COMPONENTS.md` | Step-by-step guide for adding new parts |

---

## Running the Tools

### Validate Component Database (Nexar API)
Uses your free Nexar Evaluation tier (1,000 lifetime part lookups).
Each run uses ~24 lookups.

```bash
cd python
export NEXAR_CLIENT_ID="72145a80-f6c2-46e1-9d5a-b684766e7cf4"
export NEXAR_CLIENT_SECRET="your_secret_here"
python3 validate_components.py
```

### Validate Data Files (Node.js)
Checks JSON structure, required fields, cross-references:
```bash
node server/validate.js
node server/check_component.js ESP32-WROOM-32E
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

Required for different features:
- `NEXAR_CLIENT_ID` / `NEXAR_CLIENT_SECRET` — component validation
- `JLCPCB_API_KEY` — fab ordering (when ready)
- `DIGIKEY_CLIENT_ID` / `DIGIKEY_CLIENT_SECRET` — live pricing (future)

---

## VS Code Tips

- **Ctrl+Shift+P** → "Open Workspace Settings" to adjust editor config
- **Ctrl+P** → type filename to quick-open any file
- **Ctrl+Shift+F** → search across all project files
- JSON files have schema validation via `.vscode/settings.json`
- The `data/component_template.json` shows the exact schema for new parts

---

## What's Next

This is the data layer and tooling foundation. The build sequence is:

1. ✅ Component database (done — 24 parts, 6 categories)
2. ✅ Design rules engine (done — 12 rule files)
3. ✅ Validation tooling (done — Nexar + structural)
4. 🔲 API server (Express/Fastify endpoints)
5. 🔲 AI prompt pipeline (natural language → component selection)
6. 🔲 Frontend wizard UI
7. 🔲 KiCad generation engine
8. 🔲 JLCPCB fab integration
