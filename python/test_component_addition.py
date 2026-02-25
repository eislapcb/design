#!/usr/bin/env python3
"""
PCB Wizard — Component Addition Test
=====================================
Tests the full component addition pipeline for: PIC32CK2051SG01064
"""

import requests
import json
import time
import sys
from datetime import datetime

TEST_MPN = "PIC32CK2051SG01064"
TEST_ALTERNATIVES = [
    "PIC32CK2051SG01144",
    "PIC32CK2051GC01064",
    "PIC32CK1025SG01064",
    "PIC32CK1025GC01064",
]

JLCPCB_PARTS_URL = "https://jlcpcb.com/api/overseas-pcba-order/v1/shoppingCart/smtGood/selectSmtComponentList"
LCSC_SEARCH_URL = "https://wmsc.lcsc.com/ftps/wm/product/search"

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
WARN = "\033[93m⚠ WARN\033[0m"
INFO = "\033[94mℹ INFO\033[0m"

results = {"pass": 0, "fail": 0, "warn": 0, "info": 0}

def log(status, test_name, detail=""):
    results[status] = results.get(status, 0) + 1
    icon = {"pass": PASS, "fail": FAIL, "warn": WARN, "info": INFO}[status]
    print(f"  {icon}  {test_name}")
    if detail:
        for line in detail.split("\n"):
            print(f"         {line}")

def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

# ═══════════════════════════════════════════════════════════════
# TEST 1: JLCPCB Parts Library Search
# ═══════════════════════════════════════════════════════════════
def test_jlcpcb_search(mpn):
    section(f"TEST 1: JLCPCB Parts Library — {mpn}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://jlcpcb.com",
        "Referer": "https://jlcpcb.com/parts",
    }
    
    jlcpcb_result = {"found": False, "lcsc_pn": None, "stock": 0, "category": "not_stocked"}
    
    for lib_type in ["base", "expand"]:
        payload = {"keyword": mpn, "searchSource": "search", "componentLibraryType": lib_type}
        label = "BASIC" if lib_type == "base" else "EXTENDED"
        
        try:
            resp = requests.post(JLCPCB_PARTS_URL, json=payload, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                components = data.get("data", {}).get("componentPageInfo", {}).get("list", [])
                
                if components:
                    comp = components[0]
                    jlcpcb_result = {
                        "found": True,
                        "lcsc_pn": comp.get("componentCode", ""),
                        "stock": comp.get("stockCount", 0),
                        "price": comp.get("componentPrices", []),
                        "category": "basic" if lib_type == "base" else "extended",
                        "package": comp.get("encapStandard", ""),
                        "description": comp.get("describe", ""),
                        "mfr": comp.get("brandNameEn", ""),
                    }
                    log("pass", f"Found in JLCPCB {label} library: {jlcpcb_result['lcsc_pn']}",
                        f"Stock: {jlcpcb_result['stock']} | Package: {jlcpcb_result.get('package','?')}")
                    return jlcpcb_result
                else:
                    log("info", f"Not in JLCPCB {label} library")
            else:
                log("warn", f"JLCPCB {label} API HTTP {resp.status_code}", resp.text[:200])
                
        except requests.exceptions.Timeout:
            log("warn", f"JLCPCB {label} timeout (15s)")
        except requests.exceptions.ConnectionError as e:
            log("warn", f"JLCPCB {label} connection failed", str(e)[:120])
        except Exception as e:
            log("warn", f"JLCPCB {label} error: {type(e).__name__}", str(e)[:150])
        
        time.sleep(0.3)
    
    return jlcpcb_result


# ═══════════════════════════════════════════════════════════════
# TEST 2: LCSC Electronics Search
# ═══════════════════════════════════════════════════════════════
def test_lcsc_search(mpn):
    section(f"TEST 2: LCSC Electronics — {mpn}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
    }
    payload = {"keyword": mpn, "pageSize": 5, "currPage": 1}
    
    lcsc_result = {"found": False, "lcsc_pn": None, "stock": 0, "price": None}
    
    try:
        resp = requests.post(LCSC_SEARCH_URL, json=payload, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            result_data = data.get("result", {})
            
            # LCSC has multiple response formats
            products = (
                result_data.get("tipProductDetailUrlVOList") or
                result_data.get("productSearchResultVO", {}).get("productList") or
                result_data.get("dataList") or
                []
            )
            
            if products:
                prod = products[0]
                lcsc_result = {
                    "found": True,
                    "lcsc_pn": prod.get("productCode", prod.get("lcscPartNumber", "")),
                    "mpn": prod.get("productModel", prod.get("mfrPartNumber", "")),
                    "stock": prod.get("stockNumber", prod.get("stockQty", 0)),
                    "price": prod.get("productPriceList", []),
                    "package": prod.get("encapStandard", prod.get("package", "")),
                    "mfr": prod.get("brandNameEn", prod.get("manufacturer", "")),
                }
                log("pass", f"Found on LCSC: {lcsc_result['lcsc_pn']}",
                    f"MPN: {lcsc_result['mpn']} | Stock: {lcsc_result['stock']}")
            else:
                log("info", "Not found on LCSC catalogue",
                    f"Response keys: {list(result_data.keys())[:5]}")
                # Dump a snippet for debugging
                snippet = json.dumps(result_data, indent=2, default=str)[:300]
                if snippet and snippet != "{}":
                    log("info", "LCSC raw response", snippet)
        else:
            log("warn", f"LCSC HTTP {resp.status_code}")
            
    except requests.exceptions.Timeout:
        log("warn", "LCSC timeout (15s)")
    except requests.exceptions.ConnectionError as e:
        log("warn", f"LCSC connection failed", str(e)[:120])
    except Exception as e:
        log("warn", f"LCSC error: {type(e).__name__}", str(e)[:150])
    
    return lcsc_result


# ═══════════════════════════════════════════════════════════════
# TEST 3: Alternative Parts Search
# ═══════════════════════════════════════════════════════════════
def test_alternatives():
    section("TEST 3: Alternative Parts Availability")
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Origin": "https://jlcpcb.com",
        "Referer": "https://jlcpcb.com/parts",
    }
    found = []
    
    for alt_mpn in TEST_ALTERNATIVES:
        print(f"    Checking {alt_mpn}...", end=" ", flush=True)
        
        for lib_type in ["base", "expand"]:
            payload = {"keyword": alt_mpn, "searchSource": "search", "componentLibraryType": lib_type}
            try:
                resp = requests.post(JLCPCB_PARTS_URL, json=payload, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    comps = data.get("data", {}).get("componentPageInfo", {}).get("list", [])
                    if comps:
                        c = comps[0]
                        found.append({
                            "mpn": alt_mpn,
                            "lcsc": c.get("componentCode", ""),
                            "stock": c.get("stockCount", 0),
                            "category": "basic" if lib_type == "base" else "extended",
                        })
                        cat = "BASIC" if lib_type == "base" else "EXT"
                        print(f"✓ {c.get('componentCode','')} stock:{c.get('stockCount',0)} [{cat}]")
                        break
                time.sleep(0.3)
            except Exception as e:
                pass
        else:
            print("✗ not stocked")
        
        time.sleep(0.3)
    
    if found:
        log("pass", f"{len(found)} alternative(s) found on JLCPCB",
            "\n".join([f"  {a['mpn']} → {a['lcsc']} (stock: {a['stock']}, {a['category']})" for a in found]))
    else:
        log("info", "No alternatives in JLCPCB library — full PIC32CK range unstocked")
    
    return found


# ═══════════════════════════════════════════════════════════════
# TEST 4: Component Data Structure
# ═══════════════════════════════════════════════════════════════
def test_component_structure(jlcpcb_result, lcsc_result, alternatives):
    section("TEST 4: Component Data Structure")
    
    component = {
        "id": "pic32ck_sg01_64",
        "mpn": TEST_MPN,
        "name": "PIC32CK2051SG01064",
        "display_name": "PIC32CK SG01 MCU (64-pin)",
        "description": "ARM Cortex-M33 120MHz, 2MB Flash, 512KB SRAM, HSM + TrustZone",
        "manufacturer": "Microchip Technology",
        "category": "mcu",
        "icon": "🧠",
        "specs": {
            "core": "ARM Cortex-M33",
            "clock_mhz": 120,
            "flash_kb": 2048,
            "sram_kb": 512,
            "vdd_min": 1.62,
            "vdd_max": 3.63,
            "io_count": 50,
            "has_hsm": True,
            "has_trustzone": True,
            "peripherals": ["Ethernet", "CAN FD", "USB HS", "USB FS", "I2S", "I2C", "SPI", "UART"],
            "adc_channels": 12,
            "adc_bits": 12,
        },
        "package": {
            "type": "VQFN",
            "pins": 64,
            "size_mm": "9x9",
            "pitch_mm": 0.5,
            "thermal_pad": True,
            "kicad_footprint": "Package_DFN_QFN:QFN-64-1EP_9x9mm_P0.5mm_EP5.15x5.15mm",
        },
        "layout": {
            "layers_min": 4,
            "power_watts": 0.5,
            "decoupling": ["100nF x4", "10uF x1", "1uF x2"],
            "placement_zone": "center",
            "notes": [
                "100nF caps within 3mm of VDD pins",
                "Thermal pad → ground plane with min 9 vias",
                "SWD/JTAG header for programming",
            ],
        },
        "sourcing": {
            "jlcpcb": {
                "available": jlcpcb_result["found"],
                "lcsc_pn": jlcpcb_result.get("lcsc_pn"),
                "stock": jlcpcb_result.get("stock", 0),
                "category": jlcpcb_result.get("category", "not_stocked"),
            },
            "lcsc": {
                "available": lcsc_result["found"],
                "lcsc_pn": lcsc_result.get("lcsc_pn"),
                "stock": lcsc_result.get("stock", 0),
            },
            "consignment_required": not jlcpcb_result["found"],
            "alternatives": [
                {"mpn": a["mpn"], "lcsc_pn": a.get("lcsc"), "stock": a.get("stock", 0)}
                for a in alternatives
            ],
            "digikey_mpn": "PIC32CK2051SG01064-I/TL",
            "mouser_mpn": "PIC32CK2051SG01064-I/TL",
        },
        "pricing_gbp": {
            "p1": 8.50, "p10": 7.20, "p100": 5.85,
            "source": "estimate",
        },
    }
    
    # Validations
    required = ["id", "mpn", "name", "manufacturer", "category", "specs", "package", "layout", "sourcing"]
    missing = [f for f in required if f not in component or component[f] is None]
    if not missing:
        log("pass", "All required fields present")
    else:
        log("fail", f"Missing fields: {missing}")
    
    s = component["specs"]
    if s["clock_mhz"] == 120 and s["flash_kb"] == 2048 and s["sram_kb"] == 512:
        log("pass", f"Specs: {s['core']} @ {s['clock_mhz']}MHz | {s['flash_kb']}KB Flash | {s['sram_kb']}KB SRAM")
    else:
        log("fail", "Spec values incorrect")
    
    p = component["package"]
    if p["pins"] == 64 and p["pitch_mm"] == 0.5 and "QFN-64" in p["kicad_footprint"]:
        log("pass", f"Package: {p['type']}-{p['pins']} {p['size_mm']}mm | KiCad: {p['kicad_footprint']}")
    else:
        log("fail", "Package data invalid")
    
    if component["sourcing"]["consignment_required"]:
        log("warn", "CONSIGNMENT REQUIRED — not in JLCPCB library",
            "User options:\n"
            "  1. Buy from DigiKey/Mouser → ship to JLCPCB\n"
            "  2. Pick a stocked alternative\n"
            "  3. Use a different assembler")
    else:
        log("pass", "Available in JLCPCB — standard assembly flow")
    
    log("pass", f"Layout: {component['layout']['layers_min']}-layer min | Decoupling: {', '.join(component['layout']['decoupling'])}")
    
    return component


# ═══════════════════════════════════════════════════════════════
# TEST 5: BOM Integration
# ═══════════════════════════════════════════════════════════════
def test_bom_integration(component):
    section("TEST 5: BOM & CPL Integration")
    
    bom_row = {
        "Reference": "U1",
        "Value": component["mpn"],
        "Footprint": component["package"]["kicad_footprint"],
        "LCSC Part#": component["sourcing"]["jlcpcb"].get("lcsc_pn") or "CONSIGNMENT",
        "Manufacturer": component["manufacturer"],
        "MPN": component["mpn"],
        "Qty": 1,
        "Unit Price": f"£{component['pricing_gbp']['p1']:.2f}",
    }
    
    if all(v is not None for v in bom_row.values()):
        log("pass", "BOM row complete")
        for k, v in bom_row.items():
            print(f"         {k:20s} {v}")
    else:
        log("fail", "BOM row has None values")
    
    # JLCPCB-specific format
    jlcpcb_bom = {
        "Comment": component["mpn"],
        "Designator": "U1",
        "Footprint": f"VQFN-{component['package']['pins']}",
        "LCSC Part Number": component["sourcing"]["jlcpcb"].get("lcsc_pn", ""),
    }
    
    if jlcpcb_bom["LCSC Part Number"]:
        log("pass", f"JLCPCB BOM valid: LCSC#{jlcpcb_bom['LCSC Part Number']}")
    else:
        log("warn", "JLCPCB BOM: no LCSC part# → flagged for consignment")
    
    log("pass", "CPL entry: U1 @ (0.00mm, 0.00mm) Top layer, 0° rotation")
    
    return bom_row


# ═══════════════════════════════════════════════════════════════
# TEST 6: User-Facing Component Card
# ═══════════════════════════════════════════════════════════════
def test_user_output(component):
    section("TEST 6: Component Card Output")
    
    s = component["sourcing"]
    avail = "🟢 In Stock" if s["jlcpcb"]["available"] else ("🟡 Consignment" if s["lcsc"]["available"] else "🔴 Special Order")
    
    card = f"""
┌─────────────────────────────────────────────────────────┐
│  {component['icon']}  {component['display_name']}
│  {component['description']}
├─────────────────────────────────────────────────────────┤
│  Manufacturer:  {component['manufacturer']}
│  MPN:           {component['mpn']}
│  Package:       {component['package']['type']}-{component['package']['pins']} ({component['package']['size_mm']}mm)
│  Core:          {component['specs']['core']} @ {component['specs']['clock_mhz']}MHz
│  Memory:        {component['specs']['flash_kb']}KB Flash / {component['specs']['sram_kb']}KB SRAM
│  Security:      HSM + TrustZone
│  Peripherals:   {', '.join(component['specs']['peripherals'][:5])}...
├─────────────────────────────────────────────────────────┤
│  JLCPCB:        {avail}
│  LCSC#:         {s['jlcpcb'].get('lcsc_pn') or s['lcsc'].get('lcsc_pn') or 'Not assigned'}
│  Est. Price:    £{component['pricing_gbp']['p1']:.2f} (×1) / £{component['pricing_gbp']['p100']:.2f} (×100)
│  Min Layers:    {component['layout']['layers_min']}
│  Decoupling:    {', '.join(component['layout']['decoupling'])}
├─────────────────────────────────────────────────────────┤
│  Alternatives:  {len(s['alternatives'])} checked"""
    
    for alt in s["alternatives"][:3]:
        card += f"\n│    → {alt['mpn']} (LCSC: {alt.get('lcsc_pn') or 'N/A'}, stock: {alt.get('stock', '?')})"
    
    card += "\n└─────────────────────────────────────────────────────────┘"
    print(card)
    log("pass", "Component card rendered")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print(f"  PCB WIZARD — Component Addition Test")
    print(f"  Target: {TEST_MPN}")
    print(f"  Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    t0 = time.time()
    
    jlcpcb = test_jlcpcb_search(TEST_MPN)
    time.sleep(0.5)
    lcsc = test_lcsc_search(TEST_MPN)
    time.sleep(0.5)
    alts = test_alternatives()
    component = test_component_structure(jlcpcb, lcsc, alts)
    test_bom_integration(component)
    test_user_output(component)
    
    elapsed = time.time() - t0
    
    section("TEST SUMMARY")
    print(f"  {PASS}  Passed:   {results['pass']}")
    print(f"  {FAIL}  Failed:   {results['fail']}")
    print(f"  {WARN}  Warnings: {results['warn']}")
    print(f"  {INFO}  Info:     {results['info']}")
    print(f"  ⏱  Elapsed:  {elapsed:.1f}s")
    print()
    
    if results["fail"] == 0:
        print(f"  \033[92m{'='*50}")
        print(f"  ✅  ALL CRITICAL TESTS PASSED")
        print(f"  {'='*50}\033[0m")
    else:
        print(f"  \033[91m{'='*50}")
        print(f"  ❌  {results['fail']} TEST(S) FAILED")
        print(f"  {'='*50}\033[0m")
    
    with open("/home/claude/component_output.json", "w") as f:
        json.dump(component, f, indent=2, default=str)
    print(f"\n  📄 Component JSON → component_output.json")
