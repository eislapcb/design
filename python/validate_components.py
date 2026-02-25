#!/usr/bin/env python3
"""
PCB Wizard — Component Database Validator
Uses the Nexar (Octopart) GraphQL API to validate the current component
database against live supply chain data.

Usage:
    export NEXAR_CLIENT_ID="your_client_id"
    export NEXAR_CLIENT_SECRET="your_client_secret"
    python validate_components.py

Each MPN lookup counts as 1 matched part against your Nexar limit.
Current DB has ~30 parts = ~30 of your 1,000 lifetime Evaluation limit.
"""

import os
import sys
import json
import time
import requests
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# NEXAR API CONFIG
# ═══════════════════════════════════════════════════════════════
NEXAR_API_URL = "https://api.nexar.com/graphql/"
NEXAR_TOKEN_URL = "https://identity.nexar.com/connect/token"

# ═══════════════════════════════════════════════════════════════
# CURRENT PCB WIZARD COMPONENT DATABASE
# Extracted from the prototype — these are the parts we need
# to validate against live Nexar/Octopart data
# ═══════════════════════════════════════════════════════════════
COMPONENTS = {
    # ── MCU ──
    "ESP32-WROOM-32E": {
        "cat": "MCU", "manufacturer": "Espressif Systems",
        "db_price_1": 3.50, "db_price_10": 3.15, "db_price_100": 2.68,
        "dk_pn": "1965-ESP32-WROOM-32E-ND"
    },
    "RP2040": {
        "cat": "MCU", "manufacturer": "Raspberry Pi",
        "db_price_1": 1.45, "db_price_10": 1.38, "db_price_100": 1.20,
        "dk_pn": "2648-SC0914(13)-ND"
    },
    "PIC24FJ64GA004": {
        "cat": "MCU", "manufacturer": "Microchip Technology",
        "db_price_1": 2.84, "db_price_10": 2.44, "db_price_100": 2.10,
        "dk_pn": "PIC24FJ64GA004-I/PT-ND"
    },
    "ATSAMD51J20A-AU": {
        "cat": "MCU", "manufacturer": "Microchip Technology",
        "db_price_1": 5.56, "db_price_10": 4.98, "db_price_100": 4.20,
        "dk_pn": "ATSAMD51J20A-AU-ND"
    },

    # ── Power ──
    "AMS1117-3.3": {
        "cat": "Power", "manufacturer": "Advanced Monolithic Systems",
        "db_price_1": 0.45, "db_price_10": 0.36, "db_price_100": 0.28,
        "dk_pn": "LM1117IMPX-3.3/NOPB-ND"
    },
    "MP2307DN-LF-Z": {
        "cat": "Power", "manufacturer": "Monolithic Power Systems",
        "db_price_1": 1.22, "db_price_10": 1.04, "db_price_100": 0.88,
        "dk_pn": "MP2307DN-LF-Z-ND"
    },
    "MT3608": {
        "cat": "Power", "manufacturer": "Aerosemi / Xi'an Aerospacemi",
        "db_price_1": 0.88, "db_price_10": 0.74, "db_price_100": 0.60,
        "dk_pn": "MT3608-ND"
    },
    "MCP73831T-2ATI": {
        "cat": "Power", "manufacturer": "Microchip Technology",
        "db_price_1": 0.55, "db_price_10": 0.46, "db_price_100": 0.38,
        "dk_pn": "MCP73831T-2ATI/OTCT-ND"
    },
    "FUSB302BMPX": {
        "cat": "Power", "manufacturer": "onsemi",
        "db_price_1": 1.85, "db_price_10": 1.62, "db_price_100": 1.40,
        "dk_pn": "FUSB302BMPXCT-ND"
    },

    # ── Sensors ──
    "MPU-6050": {
        "cat": "Sensor", "manufacturer": "TDK InvenSense",
        "db_price_1": 2.54, "db_price_10": 2.18, "db_price_100": 1.85,
        "dk_pn": "1428-1019-1-ND"
    },
    "ICM-42688-P": {
        "cat": "Sensor", "manufacturer": "TDK InvenSense",
        "db_price_1": 3.20, "db_price_10": 2.85, "db_price_100": 2.40,
        "dk_pn": "1428-ICM-42688-P-ND"
    },
    "BME280": {
        "cat": "Sensor", "manufacturer": "Bosch Sensortec",
        "db_price_1": 3.45, "db_price_10": 3.10, "db_price_100": 2.65,
        "dk_pn": "828-1063-1-ND"
    },
    "VEML7700": {
        "cat": "Sensor", "manufacturer": "Vishay",
        "db_price_1": 1.62, "db_price_10": 1.38, "db_price_100": 1.15,
        "dk_pn": "VEML7700-TT-ND"
    },
    "TCS34725FN": {
        "cat": "Sensor", "manufacturer": "ams-OSRAM",
        "db_price_1": 2.10, "db_price_10": 1.88, "db_price_100": 1.55,
        "dk_pn": "TCS34725FN-ND"
    },

    # ── Comms ──
    "MDBT50Q-1MV2": {
        "cat": "Comms", "manufacturer": "Raytac",
        "db_price_1": 4.80, "db_price_10": 4.20, "db_price_100": 3.55,
        "dk_pn": "MDBT50Q-1MV2-ND"
    },
    "RFM95W-868S2": {
        "cat": "Comms", "manufacturer": "HopeRF",
        "db_price_1": 5.20, "db_price_10": 4.65, "db_price_100": 3.90,
        "dk_pn": "RFM95W-868S2-ND"
    },
    "FT232RL": {
        "cat": "Comms", "manufacturer": "FTDI",
        "db_price_1": 4.50, "db_price_10": 4.05, "db_price_100": 3.50,
        "dk_pn": "768-1007-1-ND"
    },
    "MCP2515-I/SO": {
        "cat": "Comms", "manufacturer": "Microchip Technology",
        "db_price_1": 1.82, "db_price_10": 1.55, "db_price_100": 1.30,
        "dk_pn": "MCP2515-I/SO-ND"
    },

    # ── Display ──
    "SSD1306": {
        "cat": "Display", "manufacturer": "Solomon Systech",
        "db_price_1": 2.50, "db_price_10": 2.15, "db_price_100": 1.80,
        "dk_pn": "SSD1306-ND"
    },
    "ILI9341": {
        "cat": "Display", "manufacturer": "ILITEK",
        "db_price_1": 3.80, "db_price_10": 3.40, "db_price_100": 2.90,
        "dk_pn": "ILI9341-ND"
    },

    # ── Motor Drivers ──
    "DRV8833PWPR": {
        "cat": "Motor", "manufacturer": "Texas Instruments",
        "db_price_1": 1.45, "db_price_10": 1.28, "db_price_100": 1.05,
        "dk_pn": "296-30391-1-ND"
    },
    "A4988SETTR-T": {
        "cat": "Motor", "manufacturer": "Allegro MicroSystems",
        "db_price_1": 2.80, "db_price_10": 2.45, "db_price_100": 2.05,
        "dk_pn": "620-1436-1-ND"
    },
    "PCA9685PW": {
        "cat": "Motor", "manufacturer": "NXP Semiconductors",
        "db_price_1": 2.35, "db_price_10": 2.08, "db_price_100": 1.75,
        "dk_pn": "568-5931-1-ND"
    },
    "DRV8302DCAR": {
        "cat": "Motor", "manufacturer": "Texas Instruments",
        "db_price_1": 5.90, "db_price_10": 5.25, "db_price_100": 4.50,
        "dk_pn": "296-30758-1-ND"
    },
}


# ═══════════════════════════════════════════════════════════════
# NEXAR CLIENT
# ═══════════════════════════════════════════════════════════════
class NexarClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()
        self.token = None

    def get_token(self):
        """Fetch OAuth2 token using client credentials."""
        resp = self.session.post(
            NEXAR_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise Exception(f"Token request failed: {resp.status_code} — {resp.text}")
        self.token = resp.json()
        return self.token

    def query(self, graphql_query: str, variables: dict = None):
        """Execute a GraphQL query against the Nexar API."""
        if not self.token:
            self.get_token()

        headers = {
            "Authorization": f"Bearer {self.token['access_token']}",
            "Content-Type": "application/json",
        }
        body = {"query": graphql_query}
        if variables:
            body["variables"] = variables

        resp = self.session.post(NEXAR_API_URL, json=body, headers=headers, timeout=90)
        data = resp.json()

        if "errors" in data:
            error_msgs = [e.get("message", "Unknown error") for e in data["errors"]]
            raise Exception(f"GraphQL errors: {'; '.join(error_msgs)}")

        return data.get("data", {})


# ═══════════════════════════════════════════════════════════════
# GRAPHQL QUERY — supMultiMatch for batching MPNs
# Uses supMultiMatch to check multiple parts in one API call.
# Each matched part still counts individually against limit,
# but it's more efficient than individual queries.
# ═══════════════════════════════════════════════════════════════
VALIDATE_QUERY = """
query ValidateParts($queries: [SupPartMatchQuery!]!) {
    supMultiMatch(queries: $queries) {
        hits
        parts {
            mpn
            name
            manufacturer { name }
            shortDescription
            totalAvail
            medianPrice1000 {
                quantity
                price
                currency
                convertedPrice
                convertedCurrency
            }
            sellers(authorizedOnly: true) {
                company { name }
                offers {
                    sku
                    inventoryLevel
                    prices {
                        quantity
                        price
                        currency
                        convertedPrice
                        convertedCurrency
                    }
                }
            }
            specs {
                attribute { name }
                value
            }
        }
    }
}
"""


def build_queries(mpn_list: list) -> list:
    """Build supMultiMatch query input from list of MPNs."""
    return [{"mpn": mpn, "limit": 1} for mpn in mpn_list]


def validate_components(nexar: NexarClient, components: dict) -> list:
    """
    Query Nexar for all component MPNs and compare against our database.
    Returns a list of validation results.
    """
    mpn_list = list(components.keys())
    total = len(mpn_list)

    print(f"\n{'='*70}")
    print(f"  PCB WIZARD — Component Database Validation")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Components to validate: {total}")
    print(f"  Nexar parts budget used: ~{total} of 1,000 lifetime")
    print(f"{'='*70}\n")

    # Batch into groups of 10 to avoid overly large queries
    BATCH_SIZE = 10
    results = []

    for i in range(0, total, BATCH_SIZE):
        batch = mpn_list[i:i+BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  Querying batch {batch_num}/{total_batches}: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}")

        queries = build_queries(batch)
        try:
            data = nexar.query(VALIDATE_QUERY, {"queries": queries})
        except Exception as e:
            print(f"  ⚠️  Batch {batch_num} failed: {e}")
            for mpn in batch:
                results.append({
                    "mpn": mpn,
                    "cat": components[mpn]["cat"],
                    "status": "ERROR",
                    "error": str(e),
                })
            continue

        # Process each result
        multi_match = data.get("supMultiMatch", [])
        for j, match_result in enumerate(multi_match):
            mpn = batch[j]
            db = components[mpn]
            hits = match_result.get("hits", 0)
            parts = match_result.get("parts", [])

            result = {
                "mpn": mpn,
                "cat": db["cat"],
                "db_manufacturer": db["manufacturer"],
                "db_price_1": db["db_price_1"],
                "db_price_100": db["db_price_100"],
                "db_dk_pn": db["dk_pn"],
            }

            if hits == 0 or not parts:
                result["status"] = "NOT FOUND"
                result["issues"] = ["Part not found in Nexar/Octopart database"]
                results.append(result)
                continue

            part = parts[0]  # Best match
            result["nexar_name"] = part.get("name", "N/A")
            result["nexar_manufacturer"] = part.get("manufacturer", {}).get("name", "N/A")
            result["nexar_description"] = part.get("shortDescription", "N/A")
            result["nexar_total_avail"] = part.get("totalAvail", 0)

            # Median price at qty 1000
            median = part.get("medianPrice1000", {})
            if median:
                result["nexar_median_price_1000"] = median.get("convertedPrice") or median.get("price")
                result["nexar_price_currency"] = median.get("convertedCurrency") or median.get("currency")

            # Count authorized sellers with stock
            sellers = part.get("sellers", [])
            stocked_sellers = 0
            for seller in sellers:
                for offer in seller.get("offers", []):
                    if offer.get("inventoryLevel", 0) > 0 or offer.get("inventoryLevel") is None:
                        stocked_sellers += 1
                        break
            result["nexar_sellers_in_stock"] = stocked_sellers

            # Key specs
            specs = part.get("specs", [])
            spec_dict = {}
            for s in specs:
                attr_name = s.get("attribute", {}).get("name", "")
                if attr_name:
                    spec_dict[attr_name] = s.get("value", "")
            result["nexar_specs"] = spec_dict

            # ── Validation checks ──
            issues = []

            # Check availability
            total_avail = part.get("totalAvail", 0) or 0
            if total_avail == 0:
                issues.append("⚠️  ZERO STOCK across all distributors")
            elif total_avail < 100:
                issues.append(f"⚠️  LOW STOCK: only {total_avail} units available")

            # Check manufacturer match
            nexar_mfr = (part.get("manufacturer", {}).get("name", "") or "").lower()
            db_mfr = db["manufacturer"].lower()
            if nexar_mfr and db_mfr not in nexar_mfr and nexar_mfr not in db_mfr:
                issues.append(f"⚠️  MANUFACTURER MISMATCH: DB='{db['manufacturer']}' vs Nexar='{part['manufacturer']['name']}'")

            # Check if pricing seems reasonable (>50% deviation is flagged)
            if result.get("nexar_median_price_1000"):
                nexar_price = float(result["nexar_median_price_1000"])
                db_price = db["db_price_100"]  # Compare to our qty 100 price
                if db_price > 0 and nexar_price > 0:
                    deviation = abs(nexar_price - db_price) / db_price * 100
                    result["price_deviation_pct"] = round(deviation, 1)
                    if deviation > 50:
                        issues.append(f"⚠️  PRICE DEVIATION: {deviation:.0f}% (DB £{db_price:.2f} vs Nexar {result['nexar_price_currency']} {nexar_price:.2f} @1000)")

            result["status"] = "OK" if not issues else "ISSUES"
            result["issues"] = issues
            results.append(result)

        # Small delay between batches to be polite
        if i + BATCH_SIZE < total:
            time.sleep(1)

    return results


def print_report(results: list):
    """Print formatted validation report."""
    ok = [r for r in results if r["status"] == "OK"]
    issues = [r for r in results if r["status"] == "ISSUES"]
    not_found = [r for r in results if r["status"] == "NOT FOUND"]
    errors = [r for r in results if r["status"] == "ERROR"]

    print(f"\n{'='*70}")
    print(f"  VALIDATION REPORT")
    print(f"{'='*70}")
    print(f"  ✅ Validated OK:    {len(ok)}")
    print(f"  ⚠️  Issues found:   {len(issues)}")
    print(f"  ❌ Not found:       {len(not_found)}")
    print(f"  🔴 API errors:      {len(errors)}")
    print(f"{'='*70}\n")

    # ── Detailed: Issues ──
    if issues:
        print(f"{'─'*70}")
        print(f"  COMPONENTS WITH ISSUES")
        print(f"{'─'*70}")
        for r in issues:
            print(f"\n  📦 {r['mpn']}  [{r['cat']}]")
            print(f"     Nexar: {r.get('nexar_name', 'N/A')}")
            print(f"     Manufacturer: {r.get('nexar_manufacturer', 'N/A')}")
            print(f"     Total available: {r.get('nexar_total_avail', 'N/A'):,}")
            print(f"     Sellers in stock: {r.get('nexar_sellers_in_stock', 'N/A')}")
            if r.get("nexar_median_price_1000"):
                print(f"     Median price @1000: {r.get('nexar_price_currency', '')} {r['nexar_median_price_1000']:.4f}")
            print(f"     DB price @1: £{r['db_price_1']:.2f}  @100: £{r['db_price_100']:.2f}")
            if r.get("price_deviation_pct") is not None:
                print(f"     Price deviation: {r['price_deviation_pct']}%")
            for issue in r["issues"]:
                print(f"     {issue}")

    # ── Detailed: Not Found ──
    if not_found:
        print(f"\n{'─'*70}")
        print(f"  COMPONENTS NOT FOUND IN NEXAR")
        print(f"{'─'*70}")
        for r in not_found:
            print(f"  ❌ {r['mpn']}  [{r['cat']}] — {r['issues'][0]}")

    # ── Detailed: API Errors ──
    if errors:
        print(f"\n{'─'*70}")
        print(f"  API ERRORS")
        print(f"{'─'*70}")
        for r in errors:
            print(f"  🔴 {r['mpn']}  [{r['cat']}] — {r.get('error', 'Unknown')}")

    # ── Summary: All OK parts ──
    if ok:
        print(f"\n{'─'*70}")
        print(f"  VALIDATED OK")
        print(f"{'─'*70}")
        for r in ok:
            avail = r.get('nexar_total_avail', 0)
            avail_str = f"{avail:,}" if avail else "?"
            print(f"  ✅ {r['mpn']:<25s} [{r['cat']:<8s}]  Stock: {avail_str:>10s}  Sellers: {r.get('nexar_sellers_in_stock', '?')}")

    # ── Price comparison table ──
    print(f"\n{'─'*70}")
    print(f"  PRICE COMPARISON (DB vs Nexar median @1000)")
    print(f"{'─'*70}")
    print(f"  {'MPN':<25s} {'DB @100':>10s} {'Nexar @1k':>12s} {'Deviation':>10s}")
    print(f"  {'─'*25} {'─'*10} {'─'*12} {'─'*10}")
    for r in results:
        if r["status"] in ("NOT FOUND", "ERROR"):
            continue
        db_p = f"£{r['db_price_100']:.2f}"
        nexar_p = f"{r.get('nexar_price_currency', '')}{r['nexar_median_price_1000']:.2f}" if r.get("nexar_median_price_1000") else "N/A"
        dev = f"{r['price_deviation_pct']}%" if r.get("price_deviation_pct") is not None else "—"
        flag = " ⚠️" if r.get("price_deviation_pct", 0) > 50 else ""
        print(f"  {r['mpn']:<25s} {db_p:>10s} {nexar_p:>12s} {dev:>10s}{flag}")

    print(f"\n{'='*70}")
    print(f"  Validation complete. Nexar parts used: ~{len(results)}")
    print(f"{'='*70}\n")


def save_json_report(results: list, filepath: str):
    """Save full results as JSON for programmatic use."""
    report = {
        "generated": datetime.now().isoformat(),
        "total_components": len(results),
        "summary": {
            "ok": len([r for r in results if r["status"] == "OK"]),
            "issues": len([r for r in results if r["status"] == "ISSUES"]),
            "not_found": len([r for r in results if r["status"] == "NOT FOUND"]),
            "errors": len([r for r in results if r["status"] == "ERROR"]),
        },
        "results": results,
    }
    with open(filepath, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  📄 JSON report saved to: {filepath}")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    client_id = os.environ.get("NEXAR_CLIENT_ID")
    client_secret = os.environ.get("NEXAR_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("\n  ❌ Missing credentials!")
        print("  Set environment variables:")
        print('    export NEXAR_CLIENT_ID="your_client_id"')
        print('    export NEXAR_CLIENT_SECRET="your_client_secret"')
        print()
        sys.exit(1)

    print(f"\n  🔑 Authenticating with Nexar...")
    nexar = NexarClient(client_id, client_secret)

    try:
        nexar.get_token()
        print(f"  ✅ Token acquired successfully")
    except Exception as e:
        print(f"  ❌ Authentication failed: {e}")
        sys.exit(1)

    # Run validation
    results = validate_components(nexar, COMPONENTS)

    # Print report
    print_report(results)

    # Save JSON
    json_path = "pcb_wizard_validation_report.json"
    save_json_report(results, json_path)


if __name__ == "__main__":
    main()
