#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runs Nexar validation using a pre-existing bearer token."""
import sys, requests, json, time
from datetime import datetime

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Paste your Nexar bearer token here (expires 24h after issue — do not commit a real token)
# Get a fresh token from https://nexar.com/api → "Get Token"
TOKEN = "NEXAR_BEARER_TOKEN_HERE"

NEXAR_API_URL = "https://api.nexar.com/graphql/"

COMPONENTS = {
    "ESP32-WROOM-32E":  {"cat": "MCU",     "manufacturer": "Espressif Systems",           "db_price_1": 3.50, "db_price_10": 3.15, "db_price_100": 2.68},
    "RP2040":           {"cat": "MCU",     "manufacturer": "Raspberry Pi",                "db_price_1": 1.45, "db_price_10": 1.38, "db_price_100": 1.20},
    "PIC24FJ64GA004-I/PT": {"cat": "MCU",   "manufacturer": "Microchip Technology",        "db_price_1": 2.84, "db_price_10": 2.44, "db_price_100": 2.10},
    "ATSAMD51J20A-AU":  {"cat": "MCU",     "manufacturer": "Microchip Technology",        "db_price_1": 5.56, "db_price_10": 4.98, "db_price_100": 4.20},
    "AMS1117-3.3":      {"cat": "Power",   "manufacturer": "Advanced Monolithic Systems", "db_price_1": 0.45, "db_price_10": 0.36, "db_price_100": 0.28},
    "MP2307DN-LF-Z":    {"cat": "Power",   "manufacturer": "Monolithic Power Systems",    "db_price_1": 1.22, "db_price_10": 1.04, "db_price_100": 0.88},
    "MT3608":           {"cat": "Power",   "manufacturer": "Aerosemi",                    "db_price_1": 0.88, "db_price_10": 0.74, "db_price_100": 0.60},
    "MCP73831T-2ATI/OT": {"cat": "Power",   "manufacturer": "Microchip Technology",        "db_price_1": 0.55, "db_price_10": 0.46, "db_price_100": 0.38},
    "FUSB302BMPX":      {"cat": "Power",   "manufacturer": "onsemi",                      "db_price_1": 1.85, "db_price_10": 1.62, "db_price_100": 1.40},
    "MPU-6050":         {"cat": "Sensor",  "manufacturer": "TDK InvenSense",              "db_price_1": 2.54, "db_price_10": 2.18, "db_price_100": 1.85},
    "ICM-42688-P":      {"cat": "Sensor",  "manufacturer": "TDK InvenSense",              "db_price_1": 3.20, "db_price_10": 2.85, "db_price_100": 2.40},
    "BME280":           {"cat": "Sensor",  "manufacturer": "Bosch Sensortec",             "db_price_1": 3.45, "db_price_10": 3.10, "db_price_100": 2.65},
    "VEML7700-TT":      {"cat": "Sensor",  "manufacturer": "Vishay",                      "db_price_1": 1.62, "db_price_10": 1.38, "db_price_100": 1.15},
    "TCS34725FN":       {"cat": "Sensor",  "manufacturer": "ams-OSRAM",                   "db_price_1": 2.10, "db_price_10": 1.88, "db_price_100": 1.55},
    "MDBT50Q-1MV2":     {"cat": "Comms",   "manufacturer": "Raytac",                      "db_price_1": 4.80, "db_price_10": 4.20, "db_price_100": 3.55},
    "RFM95W-868S2":     {"cat": "Comms",   "manufacturer": "HopeRF",                      "db_price_1": 5.20, "db_price_10": 4.65, "db_price_100": 3.90},
    "FT232RL":          {"cat": "Comms",   "manufacturer": "FTDI",                        "db_price_1": 4.50, "db_price_10": 4.05, "db_price_100": 3.50},
    "MCP2515-I/SO":     {"cat": "Comms",   "manufacturer": "Microchip Technology",        "db_price_1": 1.82, "db_price_10": 1.55, "db_price_100": 1.30},
    # SSD1306 and ILI9341 are controller ICs never sold standalone — components.json uses
    # module MPNs (SSD1306-MODULE-128X64, MSP2402-MODULE) which are generic placeholders.
    # Validate the common breakout/module MPNs instead:
    "WEA012864DWPP3N00003": {"cat": "Display", "manufacturer": "Winstar",               "db_price_1": 2.50, "db_price_10": 2.15, "db_price_100": 1.80},  # SSD1306 OLED module
    "MSP2402":              {"cat": "Display", "manufacturer": "Waveshare",              "db_price_1": 3.80, "db_price_10": 3.40, "db_price_100": 2.90},  # ILI9341 TFT module
    "DRV8833PWPR":      {"cat": "Motor",   "manufacturer": "Texas Instruments",           "db_price_1": 1.45, "db_price_10": 1.28, "db_price_100": 1.05},
    "A4988SETTR-T":     {"cat": "Motor",   "manufacturer": "Allegro MicroSystems",        "db_price_1": 2.80, "db_price_10": 2.45, "db_price_100": 2.05},
    "PCA9685PW":        {"cat": "Motor",   "manufacturer": "NXP Semiconductors",          "db_price_1": 2.35, "db_price_10": 2.08, "db_price_100": 1.75},
    "DRV8302DCAR":      {"cat": "Motor",   "manufacturer": "Texas Instruments",           "db_price_1": 5.90, "db_price_10": 5.25, "db_price_100": 4.50},
}

QUERY = """
query ValidateParts($queries: [SupPartMatchQuery!]!) {
    supMultiMatch(queries: $queries) {
        hits
        parts {
            mpn
            name
            manufacturer { name }
            shortDescription
            totalAvail
            medianPrice1000 { quantity price currency convertedPrice convertedCurrency }
            sellers(authorizedOnly: true) {
                company { name }
                offers { sku inventoryLevel prices { quantity price currency convertedPrice convertedCurrency } }
            }
        }
    }
}
"""

def nexar_query(variables):
    resp = requests.post(
        NEXAR_API_URL,
        json={"query": QUERY, "variables": variables},
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        timeout=90,
    )
    data = resp.json()
    if "errors" in data:
        raise Exception("; ".join(e.get("message", "?") for e in data["errors"]))
    return data.get("data", {})


def main():
    mpn_list = list(COMPONENTS.keys())
    total = len(mpn_list)
    BATCH = 10
    results = []

    print(f"{'='*70}")
    print(f"  PCB WIZARD — Component Database Validation")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Components: {total}  |  Batches: {(total + BATCH - 1) // BATCH}")
    print(f"{'='*70}\n")

    for i in range(0, total, BATCH):
        batch = mpn_list[i:i + BATCH]
        bn = (i // BATCH) + 1
        tb = (total + BATCH - 1) // BATCH
        preview = " ".join(batch[:4]) + (" ..." if len(batch) > 4 else "")
        print(f"  Querying batch {bn}/{tb}: {preview}")

        try:
            data = nexar_query({"queries": [{"mpn": m, "limit": 1} for m in batch]})
        except Exception as e:
            print(f"  ERROR: {e}")
            for m in batch:
                results.append({"mpn": m, "cat": COMPONENTS[m]["cat"], "status": "ERROR", "error": str(e)})
            continue

        for j, match in enumerate(data.get("supMultiMatch", [])):
            mpn = batch[j]
            db = COMPONENTS[mpn]
            parts = match.get("parts", [])

            r = {
                "mpn": mpn,
                "cat": db["cat"],
                "db_manufacturer": db["manufacturer"],
                "db_price_1": db["db_price_1"],
                "db_price_100": db["db_price_100"],
            }

            if not match.get("hits") or not parts:
                r["status"] = "NOT FOUND"
                r["issues"] = ["Not found in Nexar/Octopart"]
                results.append(r)
                continue

            p = parts[0]
            r["nexar_name"] = p.get("name", "N/A")
            r["nexar_manufacturer"] = (p.get("manufacturer") or {}).get("name", "N/A")
            r["nexar_description"] = p.get("shortDescription", "N/A")
            r["nexar_total_avail"] = p.get("totalAvail") or 0

            med = p.get("medianPrice1000") or {}
            if med:
                r["nexar_price"] = med.get("convertedPrice") or med.get("price")
                r["nexar_currency"] = med.get("convertedCurrency") or med.get("currency", "")

            stocked = sum(
                1 for s in p.get("sellers", [])
                for o in s.get("offers", [])
                if (o.get("inventoryLevel") or 0) > 0
            )
            r["stocked_sellers"] = stocked

            issues = []
            avail = r["nexar_total_avail"]
            if avail == 0:
                issues.append("ZERO STOCK across all distributors")
            elif avail < 100:
                issues.append(f"LOW STOCK: only {avail} units")

            nx_mfr = r["nexar_manufacturer"].lower()
            db_mfr = db["manufacturer"].lower()
            if nx_mfr and db_mfr not in nx_mfr and nx_mfr not in db_mfr:
                issues.append(
                    f"MANUFACTURER MISMATCH: DB=\"{db['manufacturer']}\" vs Nexar=\"{r['nexar_manufacturer']}\""
                )

            if r.get("nexar_price") and db["db_price_100"] > 0:
                dev = abs(float(r["nexar_price"]) - db["db_price_100"]) / db["db_price_100"] * 100
                r["price_dev_pct"] = round(dev, 1)
                if dev > 50:
                    issues.append(
                        f"PRICE DEVIATION {dev:.0f}%: DB £{db['db_price_100']:.2f} "
                        f"vs Nexar {r['nexar_currency']}{float(r['nexar_price']):.3f} @1000"
                    )

            r["status"] = "OK" if not issues else "ISSUES"
            r["issues"] = issues
            results.append(r)

        if i + BATCH < total:
            time.sleep(1)

    # ── Print report ──
    ok_r    = [r for r in results if r["status"] == "OK"]
    iss_r   = [r for r in results if r["status"] == "ISSUES"]
    nf_r    = [r for r in results if r["status"] == "NOT FOUND"]
    err_r   = [r for r in results if r["status"] == "ERROR"]

    print(f"\n{'='*70}")
    print(f"  VALIDATION REPORT")
    print(f"{'='*70}")
    print(f"  OK:         {len(ok_r)}")
    print(f"  Issues:     {len(iss_r)}")
    print(f"  Not found:  {len(nf_r)}")
    print(f"  Errors:     {len(err_r)}")
    print()

    if iss_r:
        print(f"  {'─'*66}")
        print(f"  COMPONENTS WITH ISSUES")
        print(f"  {'─'*66}")
        for r in iss_r:
            print(f"\n  {r['mpn']}  [{r['cat']}]")
            print(f"    Nexar:   {r.get('nexar_name', '?')}")
            print(f"    Stock:   {r.get('nexar_total_avail', '?'):,}  |  Stocked sellers: {r.get('stocked_sellers', '?')}")
            if r.get("nexar_price"):
                print(f"    Price:   {r['nexar_currency']}{float(r['nexar_price']):.4f} @1000  |  DB £{r['db_price_100']:.2f} @100")
            for issue in r["issues"]:
                print(f"    !! {issue}")

    if nf_r:
        print(f"\n  {'─'*66}")
        print(f"  NOT FOUND IN NEXAR")
        print(f"  {'─'*66}")
        for r in nf_r:
            print(f"  {r['mpn']}  [{r['cat']}]  —  {r['issues'][0]}")

    print(f"\n  {'─'*66}")
    print(f"  FULL RESULTS TABLE")
    print(f"  {'─'*66}")
    print(f"  {'MPN':<22} {'Cat':<8} {'Stock':>10}  {'Sellers':>7}  {'DB @100':>8}  {'Nexar @1k':>10}  {'Dev':>6}  Status")
    print(f"  {'-'*22} {'-'*8} {'-'*10}  {'-'*7}  {'-'*8}  {'-'*10}  {'-'*6}  {'-'*6}")
    for r in results:
        if r["status"] in ("NOT FOUND", "ERROR"):
            stock, sellers, db_p, nx_p, dev = "—", "—", "—", "—", "—"
        else:
            stock   = f"{r['nexar_total_avail']:,}"
            sellers = str(r.get("stocked_sellers", "?"))
            db_p    = f"£{r['db_price_100']:.2f}"
            nx_p    = f"{r['nexar_currency']}{float(r['nexar_price']):.3f}" if r.get("nexar_price") else "N/A"
            dev     = f"{r['price_dev_pct']}%" if r.get("price_dev_pct") is not None else "—"
        flag = " !!" if r.get("price_dev_pct", 0) > 50 else ""
        print(f"  {r['mpn']:<22} {r['cat']:<8} {stock:>10}  {sellers:>7}  {db_p:>8}  {nx_p:>10}  {dev:>6}  {r['status']}{flag}")

    print(f"\n  Nexar lookups used: ~{len(results)}")
    print(f"{'='*70}")

    with open("eisla_validation_report.json", "w") as f:
        json.dump(
            {"generated": datetime.now().isoformat(), "total": len(results), "results": results},
            f, indent=2, default=str
        )
    print(f"  JSON saved: eisla_validation_report.json\n")


if __name__ == "__main__":
    main()
