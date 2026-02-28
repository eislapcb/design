# FreeRouting

This directory must contain `freerouting.jar` (not committed — too large for git).

## Download

```bash
curl -L --ssl-no-revoke -o freerouting/freerouting.jar \
  https://github.com/freerouting/freerouting/releases/download/v2.1.0/freerouting-2.1.0.jar
```

Or download manually from:
https://github.com/freerouting/freerouting/releases/tag/v2.1.0

## Version

Tested with **v2.1.0** (April 2025).

## Usage (called by worker.js)

```bash
java -jar freerouting/freerouting.jar -de board.dsn -do board.ses
```

Timeout: 90 seconds (configurable via `FREEROUTING_TIMEOUT_MS` env var).
