# Eisla — IoT Capability Gap Analysis

## Current State: 45 Capabilities, 52 Components

Our taxonomy covers the "maker to mid-level IoT" space well. But there are significant gaps once you look at what real IoT projects actually deploy — particularly in cellular IoT, industrial protocols, and some common sensing categories that come up constantly in commercial IoT.

---

## Gap Analysis by IoT Market Segment

### 1. Smart Agriculture / Environmental Monitoring
**What customers ask for:** soil moisture, weather station, remote field monitoring, irrigation control
**What we have:** sense_temperature, sense_humidity, sense_pressure, sense_light, sense_gps, lora, power_solar, power_lipo, low_power_sleep
**What's missing:**
- **Soil moisture sensing** — extremely common IoT use case, no analogue soil probe input
- **NB-IoT / cellular** — farms don't have WiFi. LoRa needs a gateway. Cellular is the go-to for remote deployment
- **Current loop (4-20mA) input** — existing industrial sensors (flow, level, pressure) almost universally output 4-20mA

### 2. Smart Home / Building Automation
**What customers ask for:** smart thermostat, door sensor, smart plug, lighting control, security
**What we have:** wifi, bluetooth, zigbee, sense_temperature, relay, led_single, buttons, display_oled
**What's missing:**
- **Thread** — the transport layer for Matter (the smart home standard backed by Apple/Google/Amazon). Thread is replacing Zigbee for new devices. nRF52840 supports it, but we don't surface it as a capability
- **IR transmitter/receiver** — controlling existing appliances (ACs, TVs). Very common in smart home
- **PIR motion detection** — the most basic security/occupancy sensor, not in our taxonomy
- **NFC** — used for device provisioning in Matter 1.4+, also common for tap-to-pair

### 3. Asset Tracking / Logistics
**What customers ask for:** GPS tracker, fleet management, cold chain monitoring, package tracking
**What we have:** sense_gps, bluetooth, lora, power_lipo
**What's missing:**
- **Cellular (NB-IoT / LTE-M)** — GPS tracker without cellular is useless unless LoRa gateway nearby
- **Accelerometer/vibration for tamper detection** — we have IMU, which works, but the use case framing matters

### 4. Industrial IoT (IIoT)
**What customers ask for:** sensor gateway, Modbus adapter, PLC bridge, machine monitoring
**What we have:** can_bus, ethernet, uart
**What's missing:**
- **RS-485** — the physical layer for Modbus RTU, the dominant industrial protocol. Huge gap
- **4-20mA current loop input** — the single most common industrial sensor output standard globally
- **Isolated digital I/O** — industrial control needs optically isolated inputs/outputs
- **DIN rail mount** — not a capability per se, but a board form factor option we should consider

### 5. Wearables / Health Monitoring
**What customers ask for:** fitness tracker, health monitor, smart watch
**What we have:** bluetooth, sense_motion_imu, display_oled, low_power_sleep, power_lipo
**What's missing:**
- **Heart rate / SpO2 (MAX30102)** — very popular hobbyist/prototype request
- **Haptic/vibration motor** — LRA or ERM motor for wearable feedback

### 6. Energy / Smart Metering
**What customers ask for:** energy monitor, smart plug, solar monitor
**What we have:** power_mains, power_solar, relay, ethernet, wifi
**What's missing:**
- **Current sensing (non-invasive CT clamp / INA219)** — monitoring mains power draw
- **NB-IoT** — smart meters are the #1 NB-IoT use case globally (1.9 billion endpoints in 2024)

---

## Recommended New Capabilities — Prioritised

### Tier A: Add Now (High demand, straightforward hardware)

| Capability ID | Display Label | Group | Rationale |
|---|---|---|---|
| `nbiot` | NB-IoT (cellular) | connectivity | #1 gap. 1.9B endpoints. Essential for any remote/outdoor IoT. Uses Quectel BC660K or SIM7000 modules. Needs SIM slot + antenna |
| `lte_m` | LTE-M (cellular) | connectivity | Higher bandwidth sibling of NB-IoT. Often same module supports both. Critical for asset tracking |
| `rs485` | RS-485 / Modbus | connectivity | Industrial standard. MAX485 transceiver, dirt cheap. Opens entire IIoT market |
| `thread` | Thread | connectivity | Matter transport layer. nRF52840 already supports it — just need to surface the capability and let resolver know |
| `sense_pir` | PIR motion detection | sensing | HC-SR501 or EKMC1603111. Most basic security sensor. Massive smart home demand |
| `sense_current` | Current / power monitoring | sensing | INA219 or CT clamp input. Smart energy is a huge IoT category |
| `ir_transceiver` | IR transmit/receive | output | TSOP38238 + IR LED. Smart home universal remote. Very low cost addition |

### Tier B: Add Before Launch (Solid demand, slightly more niche)

| Capability ID | Display Label | Group | Rationale |
|---|---|---|---|
| `current_loop_4_20ma` | 4-20mA analogue input | sensing | Industrial sensor standard. Needs precision resistor + ADC. Opens IIoT gateway market |
| `nfc` | NFC | connectivity | Device provisioning, Matter 1.4 onboarding, tap-to-pair. PN532 or ST25DV |
| `sense_heartrate` | Heart rate / SpO2 | sensing | MAX30102. Very popular in wearable prototypes |
| `vibration_motor` | Haptic feedback / vibration | output | LRA motor + DRV2605 driver. Wearable essential |
| `sense_soil_moisture` | Soil moisture | sensing | Analogue probe input. Smart agriculture staple |
| `sense_weight` | Weight / load cell | sensing | HX711 amplifier. Smart scales, tank level, industrial weighing |

### Tier C: Consider for Post-Launch

| Capability ID | Display Label | Group | Rationale |
|---|---|---|---|
| `sub_ghz` | Sub-GHz radio (433/868MHz) | connectivity | CC1101 or similar. ISM band, no licence. Simpler than LoRa for point-to-point |
| `i2s_audio` | I2S digital audio | output | Beyond buzzer — proper audio playback/recording. MAX98357A |
| `sense_uv` | UV index | sensing | VEML6075. Weather stations and outdoor monitoring |
| `sense_sound` | Sound level / microphone | sensing | INMP441 MEMS mic. Noise monitoring, voice trigger |
| `sense_vibration` | Vibration monitoring | sensing | ADXL345 or dedicated vibration sensor. Predictive maintenance |
| `isolated_io` | Isolated digital I/O | output | Optocoupler isolated inputs. Industrial control safety |
| `power_poe` | Power over Ethernet | power | IEEE 802.3af. Ethernet-powered devices, IP cameras |

---

## Cellular IoT Deep Dive: NB-IoT vs LTE-M

This is the single biggest gap in our taxonomy. Here's why it matters:

**NB-IoT** (Narrowband IoT):
- 1.9 billion endpoints deployed by 2024
- 470+ live networks in 82 countries
- Ultra-low power: ~800nA in PSM mode
- Peak: 26kbps down, 62.5kbps up
- Use cases: smart metering, parking, agriculture, asset tracking
- UK coverage: strong (Vodafone, Three)
- Module: Quectel BC660K-GL (~£4.50), 17.7 × 15.8 × 2.0mm

**LTE-M** (Cat-M1):
- Higher bandwidth than NB-IoT (375kbps down, 300kbps up)
- Supports VoLTE (voice calls)
- Lower latency than NB-IoT
- Better for real-time tracking and firmware OTA
- Module: SIM7080G does both NB-IoT + LTE-M + GNSS (~£7.50)

**Implementation for Eisla:**
Both need: UART connection to MCU, SIM card slot (nano-SIM), antenna (LTE band), and adequate power supply (peak current can hit 500mA during transmission). The resolver should auto-add a nano-SIM holder and antenna connector when either cellular capability is selected — same pattern as LoRa auto-adding SMA connector.

---

## Impact on Resolver and Component Database

Adding Tier A capabilities means adding approximately:
- **3-4 new components** (BC660K NB-IoT module, MAX485 RS-485 transceiver, PIR sensor, INA219 current sensor)
- **1 new connector** (nano-SIM card holder for cellular)
- **2-3 passives** (IR LED, IR receiver, precision shunt resistor)
- **Thread** needs no new component — nRF52840 already supports it, just add the capability mapping

The resolver auto-add rules need extending:
- `nbiot` or `lte_m` → auto-add nano-SIM holder + LTE antenna connector
- `rs485` → auto-add MAX485 transceiver + 120Ω termination resistor
- `sense_current` → auto-add INA219 (if I2C) or shunt resistor + ADC channel
- `thread` → prefer nRF52840 as MCU (already highest `zigbee` score, same silicon)
- `ir_transceiver` → auto-add IR LED + TSOP receiver + current limiting resistor

---

## Recommendation

**For Session 1 completion:** Add the 7 Tier A capabilities to capabilities.json now, plus their components. This positions Eisla for the real IoT market rather than just the maker/hobbyist segment.

**Total after additions:** ~52 capabilities, ~60 components — comprehensive enough for launch without being unwieldy.
