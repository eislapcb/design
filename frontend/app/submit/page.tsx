'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

const EXAMPLES = [
  'A WiFi sensor hub that reads temperature and humidity over I2C and posts to MQTT.',
  'USB-C dev board with an RP2040, SPI flash, and a TC2050 SWD debug header.',
  'Motor controller with an ESP32, dual H-bridge, BLE, and USB-C charging.',
  'Low-power ATmega328P data logger with an SD card and a 3.7 V LiPo battery.',
]

function TierHint({ text }: { text: string }) {
  const lower = text.toLowerCase()
  const tier =
    lower.includes('stm32h') || lower.includes('imxrt') || lower.includes('ethernet')
      ? 3
      : lower.includes('esp32') || lower.includes('rp2040') || lower.includes('nrf') || lower.includes('wifi') || lower.includes('bluetooth') || lower.includes('ble')
      ? 2
      : lower.length > 20
      ? 1
      : null

  if (!tier) return null

  const labels: Record<number, { label: string; price: string; style: string }> = {
    1: { label: 'Tier 1 — Simple MCU',   price: '£499', style: 'bg-teal-light text-teal' },
    2: { label: 'Tier 2 — Standard MCU', price: '£599', style: 'bg-teal-light text-teal' },
    3: { label: 'Tier 3 — Advanced MCU', price: '£749', style: 'bg-copper-light text-copper' },
  }

  const { label, price, style } = labels[tier]

  return (
    <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded text-xs font-mono ${style}`}>
      <span>{label}</span>
      <span className="font-bold">{price} design fee</span>
    </div>
  )
}

export default function Submit() {
  const router = useRouter()
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)

  function handleExampleClick(example: string) {
    setDescription(example)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!description.trim()) return
    setLoading(true)
    // Simulate pipeline generation (1.5 s) then go to the review page
    await new Promise(r => setTimeout(r, 1500))
    router.push('/review/proj_003')
  }

  return (
    <div className="p-10 max-w-2xl">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-copper mb-1">New Project</p>
      <h1 className="text-3xl font-bold text-teal mb-2">Describe your board</h1>
      <p className="text-mid-grey text-sm leading-relaxed mb-8">
        Tell us what you need in plain English. No jargon required — just describe
        what the board should do, any components you have in mind, and any constraints.
      </p>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Main input */}
        <div>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            placeholder="e.g. A WiFi-enabled temperature logger that runs on a LiPo battery and posts readings to an MQTT broker every 30 seconds."
            rows={6}
            required
            className="w-full border-2 border-teal-light rounded-xl p-4 text-near-black text-sm leading-relaxed resize-none focus:outline-none focus:border-teal transition-colors font-sans placeholder:text-light-grey"
          />
          {/* Live tier hint */}
          <div className="mt-2 h-7">
            <TierHint text={description} />
          </div>
        </div>

        {/* Examples */}
        <div>
          <p className="text-xs font-mono uppercase tracking-[0.2em] text-mid-grey mb-3">Examples — click to use</p>
          <div className="space-y-2">
            {EXAMPLES.map(ex => (
              <button
                key={ex}
                type="button"
                onClick={() => handleExampleClick(ex)}
                className="w-full text-left text-sm text-mid-grey bg-off-white hover:bg-teal-light hover:text-teal rounded-lg px-4 py-2.5 transition-colors leading-relaxed"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>

        {/* Submit */}
        <div className="flex items-center gap-4 pt-2">
          <button
            type="submit"
            disabled={!description.trim() || loading}
            className="bg-copper text-white font-bold px-6 py-3 rounded-lg hover:bg-[#b36c38] transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" opacity=".25"/>
                  <path d="M21 12a9 9 0 00-9-9"/>
                </svg>
                Generating design…
              </>
            ) : (
              'Generate design →'
            )}
          </button>
          <p className="text-xs text-light-grey">
            Usually ready to review within a few minutes.
          </p>
        </div>
      </form>

      {/* What happens next */}
      <div className="mt-12 border-t border-teal-light pt-8">
        <p className="text-xs font-mono uppercase tracking-[0.2em] text-mid-grey mb-4">What happens next</p>
        <ol className="space-y-3">
          {[
            ['Generate', 'Our AI designs the schematic from your description.'],
            ['Review',   'An engineer checks the design (Tier 2 & 3). You approve or request changes.'],
            ['Choose',   'Pick your fab from JLCPCB, PCBWay, PCBTrain, or Eurocircuits.'],
            ['Deliver',  'We place the order and manage delivery to your door.'],
          ].map(([title, desc], i) => (
            <li key={title} className="flex items-start gap-4">
              <span className="w-6 h-6 rounded-full bg-teal text-white text-xs font-bold font-mono flex items-center justify-center flex-shrink-0 mt-0.5">
                {i + 1}
              </span>
              <div>
                <span className="font-bold text-teal text-sm">{title} — </span>
                <span className="text-sm text-mid-grey">{desc}</span>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
