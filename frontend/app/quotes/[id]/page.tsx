'use client'

import { useState } from 'react'
import { use } from 'react'
import { projects, fabQuotes } from '@/lib/mock-data'
import type { FabQuote, ShippingOption } from '@/lib/types'

function CountryFlag({ country }: { country: string }) {
  const flags: Record<string, string> = {
    'China': '🇨🇳',
    'United Kingdom': '🇬🇧',
    'Belgium': '🇧🇪',
  }
  return <span>{flags[country] ?? '🌍'}</span>
}

function FabCard({
  quote,
  selected,
  onSelect,
}: {
  quote: FabQuote
  selected: boolean
  onSelect: (fab: string, shipping: ShippingOption) => void
}) {
  const [shipping, setShipping] = useState<ShippingOption>(quote.shippingOptions[0])
  const total = quote.boardCost + quote.assemblyCost + quote.componentsCost + shipping.price

  return (
    <div
      className={`bg-white rounded-xl border-2 p-6 flex flex-col gap-4 transition-all ${
        selected
          ? 'border-copper shadow-lg shadow-copper/10'
          : 'border-teal-light hover:border-teal/40'
      } ${quote.recommended ? 'relative' : ''}`}
    >
      {quote.recommended && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-copper text-white text-xs font-mono font-bold px-3 py-1 rounded-full tracking-widest uppercase">
          Best value
        </div>
      )}

      {/* Fab header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-teal flex items-center justify-center text-white font-bold font-mono text-sm">
            {quote.abbr}
          </div>
          <div>
            <p className="font-bold text-teal text-base">{quote.fab}</p>
            <p className="text-xs text-mid-grey">
              <CountryFlag country={quote.country} /> {quote.country}
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold text-teal">£{total}</p>
          <p className="text-xs text-mid-grey">inc. shipping</p>
        </div>
      </div>

      {/* Cost breakdown */}
      <div className="space-y-1.5 text-sm border-t border-b border-teal-light py-3">
        {[
          ['Bare PCB',   quote.boardCost],
          ['Assembly',   quote.assemblyCost],
          ['Components', quote.componentsCost],
        ].map(([label, cost]) => (
          <div key={label as string} className="flex justify-between">
            <span className="text-mid-grey">{label as string}</span>
            <span className="font-mono text-near-black">£{cost as number}</span>
          </div>
        ))}
      </div>

      {/* Lead time */}
      <div className="flex items-center gap-2 text-sm">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" className="text-teal flex-shrink-0">
          <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
        </svg>
        <span className="text-mid-grey">Lead time:</span>
        <span className="font-bold text-teal">{quote.leadTimeDays} days</span>
      </div>

      {/* Shipping selector */}
      <div>
        <p className="text-xs text-mid-grey mb-2 uppercase tracking-wider font-mono">Shipping</p>
        <div className="space-y-1.5">
          {quote.shippingOptions.map(opt => (
            <label
              key={opt.name}
              className={`flex items-center justify-between p-2.5 rounded-lg border cursor-pointer transition-colors text-sm ${
                shipping.name === opt.name
                  ? 'border-teal bg-teal-light'
                  : 'border-teal-light hover:border-teal/30'
              }`}
            >
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  name={`shipping-${quote.fab}`}
                  checked={shipping.name === opt.name}
                  onChange={() => setShipping(opt)}
                  className="accent-teal"
                />
                <span className={shipping.name === opt.name ? 'text-teal font-bold' : 'text-near-black'}>
                  {opt.name}
                </span>
                <span className="text-mid-grey text-xs">({opt.days}d)</span>
              </div>
              <span className="font-mono text-near-black">£{opt.price}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Select button */}
      <button
        onClick={() => onSelect(quote.fab, shipping)}
        className={`w-full py-2.5 rounded-lg font-bold text-sm transition-colors ${
          selected
            ? 'bg-copper text-white'
            : 'bg-teal-light text-teal hover:bg-teal hover:text-white'
        }`}
      >
        {selected ? '✓ Selected' : 'Select this fab'}
      </button>
    </div>
  )
}

export default function QuotesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [selectedFab, setSelectedFab] = useState<string | null>(null)
  const [selectedShipping, setSelectedShipping] = useState<ShippingOption | null>(null)
  const [ordered, setOrdered] = useState(false)

  const project = projects.find(p => p.id === id)
  const quotes = fabQuotes[id] ?? []

  if (!project) {
    return <div className="p-10"><h1 className="text-2xl font-bold text-teal">Project not found</h1></div>
  }

  function handleSelect(fab: string, shipping: ShippingOption) {
    setSelectedFab(fab)
    setSelectedShipping(shipping)
  }

  function handleOrder() {
    setOrdered(true)
  }

  if (ordered) {
    return (
      <div className="p-10 flex items-center justify-center min-h-[60vh]">
        <div className="text-center max-w-md">
          <div className="w-16 h-16 rounded-full bg-teal flex items-center justify-center mx-auto mb-4">
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
              <path d="M20 6L9 17l-5-5" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-teal mb-2">Order placed with {selectedFab}</h2>
          <p className="text-mid-grey leading-relaxed">
            We&apos;ve placed the manufacturing order on your behalf. You&apos;ll receive a tracking link
            by email once your boards ship.
          </p>
          <p className="mt-4 text-sm text-copper font-bold">
            Estimated delivery: {selectedShipping?.days} day{selectedShipping && selectedShipping.days > 1 ? 's' : ''} after completion
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-10 max-w-6xl">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-copper mb-1">Manufacturing Quotes</p>
      <h1 className="text-3xl font-bold text-teal mb-1">{project.name}</h1>
      <p className="text-mid-grey text-sm mb-8">
        Side-by-side quotes from our manufacturing partners. Choose the price and lead time that suits you.
        We place the order and manage delivery.
      </p>

      {/* Quote cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5 mb-8">
        {quotes.map(q => (
          <FabCard
            key={q.fab}
            quote={q}
            selected={selectedFab === q.fab}
            onSelect={handleSelect}
          />
        ))}
      </div>

      {/* Place order bar */}
      {selectedFab && (
        <div className="sticky bottom-6 bg-white border border-teal/20 rounded-xl shadow-xl px-6 py-4 flex items-center justify-between gap-4">
          <div>
            <p className="font-bold text-teal">
              {selectedFab} · {selectedShipping?.name}
            </p>
            <p className="text-sm text-mid-grey">
              {quotes.find(q => q.fab === selectedFab)?.leadTimeDays} day lead time
              · ships in {selectedShipping?.days} day{selectedShipping && selectedShipping.days > 1 ? 's' : ''}
            </p>
          </div>
          <button
            onClick={handleOrder}
            className="bg-copper text-white font-bold px-8 py-3 rounded-lg hover:bg-[#b36c38] transition-colors text-sm whitespace-nowrap"
          >
            Place order →
          </button>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-xs text-light-grey mt-4 leading-relaxed">
        Quotes include 5 assembled prototype boards. Manufacturing cost is separate from the Eisla design fee (£{project.price} already paid).
        Prices are estimates and may vary slightly at checkout due to component availability.
      </p>
    </div>
  )
}
