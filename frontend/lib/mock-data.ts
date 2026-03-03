import type { Project, DesignSummary, FabQuote } from './types'

export const projects: Project[] = [
  {
    id: 'proj_001',
    name: 'WiFi Temperature Logger',
    description:
      'A WiFi-enabled temperature and humidity sensor that logs data to the cloud. Uses an ESP32 with an SHT31 sensor and a LiPo battery with USB-C charging.',
    tier: 2,
    status: 'delivered',
    createdAt: '2026-01-15',
    updatedAt: '2026-02-10',
    price: 599,
    mcu: 'ESP32',
  },
  {
    id: 'proj_002',
    name: 'BLE Motor Controller',
    description:
      'Dual H-bridge motor controller for a small robot. ESP32 with Bluetooth LE, dual PWM outputs, current sensing, and USB-C charging.',
    tier: 2,
    status: 'manufacturing',
    createdAt: '2026-02-01',
    updatedAt: '2026-02-28',
    price: 599,
    mcu: 'ESP32',
  },
  {
    id: 'proj_003',
    name: 'RGB LED Matrix Driver',
    description:
      'RP2040-based driver for a 64×32 RGB LED matrix. USB-C power input, SPI interface to the matrix, SWD debug header, and status LED.',
    tier: 2,
    status: 'awaiting_approval',
    createdAt: '2026-02-20',
    updatedAt: '2026-03-01',
    price: 599,
    mcu: 'RP2040',
  },
  {
    id: 'proj_004',
    name: 'Industrial Sensor Hub',
    description:
      'STM32H7-based multi-channel sensor hub with Gigabit Ethernet, USB HS, and four independent SPI channels for high-speed IMUs.',
    tier: 3,
    status: 'in_review',
    createdAt: '2026-02-25',
    updatedAt: '2026-03-02',
    price: 749,
    mcu: 'STM32H743',
  },
]

export const designSummaries: Record<string, DesignSummary> = {
  proj_003: {
    projectId: 'proj_003',
    boardDimensions: '75 × 55 mm',
    layers: 4,
    mcu: 'RP2040 (Raspberry Pi)',
    powerInput: 'USB-C 5 V → 3.3 V LDO (AMS1117)',
    interfaces: [
      'USB-C (power + programming)',
      'SPI (LED matrix output)',
      'SWD (debug + flash)',
    ],
    componentCount: 47,
    components: [
      { name: 'RP2040', value: 'MCU', quantity: 1 },
      { name: 'AMS1117-3.3', value: '3.3 V LDO regulator', quantity: 1 },
      { name: 'GCT USB4085', value: 'USB-C receptacle', quantity: 1 },
      { name: 'Decoupling capacitor', value: '100 nF', quantity: 12 },
      { name: 'Bulk capacitor', value: '10 µF', quantity: 4 },
      { name: 'Pull-up / bias resistor', value: '10 kΩ', quantity: 6 },
      { name: 'Status LED', value: 'Green 0402', quantity: 1 },
      { name: 'LED current-limit resistor', value: '330 Ω', quantity: 1 },
      { name: 'TC2050 debug header', value: 'SWD', quantity: 1 },
      { name: 'IDC connector', value: '2×8 pin LED matrix', quantity: 2 },
    ],
    notes: [
      'Reset circuit: 10 kΩ pull-up to 3.3 V, 100 nF filter cap to GND',
      '4-layer stackup: signal / GND / 3V3 power / signal',
      'USB D+ / D− routed as 90 Ω differential pair, <5 mm length mismatch',
      'All decoupling caps placed within 0.5 mm of IC power pins',
    ],
  },
}

export const fabQuotes: Record<string, FabQuote[]> = {
  proj_003: [
    {
      fab: 'JLCPCB',
      abbr: 'JL',
      country: 'China',
      boardCost: 18,
      assemblyCost: 67,
      componentsCost: 44,
      leadTimeDays: 12,
      recommended: true,
      shippingOptions: [
        { name: 'DHL Express', price: 18, days: 3 },
        { name: 'Standard Post', price: 6, days: 14 },
      ],
    },
    {
      fab: 'PCBWay',
      abbr: 'PW',
      country: 'China',
      boardCost: 22,
      assemblyCost: 78,
      componentsCost: 48,
      leadTimeDays: 10,
      shippingOptions: [
        { name: 'DHL Express', price: 20, days: 3 },
        { name: 'Standard Post', price: 8, days: 12 },
      ],
    },
    {
      fab: 'PCBTrain',
      abbr: 'PT',
      country: 'United Kingdom',
      boardCost: 35,
      assemblyCost: 110,
      componentsCost: 52,
      leadTimeDays: 8,
      shippingOptions: [
        { name: 'Royal Mail 1st Class', price: 4, days: 1 },
        { name: 'DPD Next Day', price: 8, days: 1 },
      ],
    },
    {
      fab: 'Eurocircuits',
      abbr: 'EC',
      country: 'Belgium',
      boardCost: 42,
      assemblyCost: 125,
      componentsCost: 58,
      leadTimeDays: 7,
      shippingOptions: [
        { name: 'DHL Express', price: 15, days: 2 },
        { name: 'Standard Post', price: 9, days: 5 },
      ],
    },
  ],
}
