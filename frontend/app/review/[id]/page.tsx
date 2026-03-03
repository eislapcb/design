'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { use } from 'react'
import { projects, designSummaries } from '@/lib/mock-data'

// PCB render placeholder — shows a stylised board outline with copper traces
function BoardRender() {
  return (
    <div className="w-full aspect-[4/3] bg-teal rounded-xl flex items-center justify-center relative overflow-hidden">
      {/* Grid overlay — mimics the hero section grid from the landing page */}
      <div
        className="absolute inset-0 opacity-10"
        style={{
          backgroundImage:
            'repeating-linear-gradient(0deg,transparent,transparent 39px,rgba(255,255,255,1) 39px,rgba(255,255,255,1) 40px),repeating-linear-gradient(90deg,transparent,transparent 39px,rgba(255,255,255,1) 39px,rgba(255,255,255,1) 40px)',
        }}
      />
      {/* Stylised PCB outline */}
      <svg viewBox="0 0 320 240" className="w-4/5 opacity-80">
        {/* Board outline */}
        <rect x="20" y="20" width="280" height="200" rx="8" fill="none" stroke="#C27840" strokeWidth="2" />
        {/* Corner mounting holes */}
        {[[34,34],[286,34],[34,206],[286,206]].map(([cx,cy],i) => (
          <circle key={i} cx={cx} cy={cy} r="6" fill="none" stroke="#C27840" strokeWidth="1.5" />
        ))}
        {/* MCU footprint */}
        <rect x="110" y="80" width="100" height="80" rx="4" fill="rgba(194,120,64,0.15)" stroke="#C27840" strokeWidth="1.5" />
        <text x="160" y="127" textAnchor="middle" fill="#C27840" fontSize="10" fontFamily="monospace">RP2040</text>
        {/* Traces */}
        <polyline points="40,120 90,120 110,120" fill="none" stroke="#C27840" strokeWidth="1.5" opacity="0.6"/>
        <polyline points="210,100 250,100 280,100" fill="none" stroke="#C27840" strokeWidth="1.5" opacity="0.6"/>
        <polyline points="160,160 160,190 240,190" fill="none" stroke="#C27840" strokeWidth="1.5" opacity="0.6"/>
        <polyline points="110,140 60,140 60,190 90,190" fill="none" stroke="#C27840" strokeWidth="1.5" opacity="0.6"/>
        {/* Pads */}
        {[[40,120],[280,100],[240,190],[90,190]].map(([cx,cy],i) => (
          <circle key={i} cx={cx} cy={cy} r="5" fill="#C27840" opacity="0.8" />
        ))}
        {/* USB-C connector */}
        <rect x="270" y="108" width="20" height="24" rx="3" fill="rgba(194,120,64,0.2)" stroke="#C27840" strokeWidth="1.5"/>
        <text x="280" y="122" textAnchor="middle" fill="#C27840" fontSize="6" fontFamily="monospace">USB-C</text>
        {/* Debug header */}
        <rect x="30" y="108" width="24" height="16" rx="2" fill="rgba(194,120,64,0.2)" stroke="#C27840" strokeWidth="1.5"/>
        <text x="42" y="119" textAnchor="middle" fill="#C27840" fontSize="6" fontFamily="monospace">SWD</text>
      </svg>
      {/* Corner label */}
      <div className="absolute bottom-3 right-4 font-mono text-xs text-copper/60 tracking-wider">
        3D RENDER PREVIEW
      </div>
    </div>
  )
}

export default function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const [changeText, setChangeText] = useState('')
  const [approved, setApproved] = useState(false)
  const [changeMode, setChangeMode] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const project = projects.find(p => p.id === id)
  const summary = designSummaries[id]

  if (!project || !summary) {
    return (
      <div className="p-10">
        <h1 className="text-2xl font-bold text-teal">Project not found</h1>
      </div>
    )
  }

  function handleApprove() {
    setApproved(true)
    setTimeout(() => router.push(`/quotes/${id}`), 1200)
  }

  function handleChangeSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitted(true)
  }

  if (approved) {
    return (
      <div className="p-10 flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="w-16 h-16 rounded-full bg-teal flex items-center justify-center mx-auto mb-4">
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
              <path d="M20 6L9 17l-5-5" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-teal mb-2">Design approved</h2>
          <p className="text-mid-grey">Taking you to fab quotes…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-10 max-w-6xl">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-copper mb-1">Design Review</p>
      <h1 className="text-3xl font-bold text-teal mb-1">{project.name}</h1>
      <p className="text-mid-grey text-sm mb-8">
        Review the design below. Approve to proceed to manufacturing, or request changes.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left — 3D render */}
        <div className="space-y-4">
          <BoardRender />
          <p className="text-xs text-light-grey text-center font-mono">
            Schematic-accurate render · {summary.boardDimensions} · {summary.layers}-layer
          </p>

          {/* Key specs */}
          <div className="bg-white rounded-xl border border-teal-light p-5 space-y-3">
            {[
              ['MCU',        summary.mcu],
              ['Board size', summary.boardDimensions],
              ['Layers',     `${summary.layers}-layer`],
              ['Power',      summary.powerInput],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between text-sm">
                <span className="text-mid-grey">{label}</span>
                <span className="font-bold text-teal">{value}</span>
              </div>
            ))}
            <div className="pt-2 border-t border-teal-light">
              <p className="text-xs text-mid-grey mb-1.5">Interfaces</p>
              <div className="flex flex-wrap gap-1.5">
                {summary.interfaces.map(i => (
                  <span key={i} className="bg-teal-light text-teal text-xs px-2 py-0.5 rounded font-mono">
                    {i}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Right — design summary */}
        <div className="space-y-5">
          {/* Components */}
          <div className="bg-white rounded-xl border border-teal-light p-5">
            <h2 className="text-copper font-bold text-sm uppercase tracking-wider mb-3">
              Components ({summary.componentCount} total)
            </h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-teal-light">
                  <th className="text-left text-mid-grey font-normal pb-2">Component</th>
                  <th className="text-left text-mid-grey font-normal pb-2">Value</th>
                  <th className="text-right text-mid-grey font-normal pb-2">Qty</th>
                </tr>
              </thead>
              <tbody>
                {summary.components.map(c => (
                  <tr key={c.name} className="border-b border-off-white last:border-0">
                    <td className="py-1.5 text-near-black">{c.name}</td>
                    <td className="py-1.5 text-mid-grey font-mono text-xs">{c.value}</td>
                    <td className="py-1.5 text-right text-near-black font-mono">{c.quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Engineer notes */}
          <div className="bg-white rounded-xl border border-teal-light p-5">
            <h2 className="text-copper font-bold text-sm uppercase tracking-wider mb-3">Engineer Notes</h2>
            <ul className="space-y-2">
              {summary.notes.map(note => (
                <li key={note} className="flex items-start gap-2 text-sm text-mid-grey">
                  <span className="text-copper mt-0.5">•</span>
                  <span>{note}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Actions */}
          {!changeMode && !submitted && (
            <div className="flex gap-3">
              <button
                onClick={handleApprove}
                className="flex-1 bg-copper text-white font-bold py-3 rounded-lg hover:bg-[#b36c38] transition-colors text-sm"
              >
                Approve design →
              </button>
              <button
                onClick={() => setChangeMode(true)}
                className="flex-1 bg-white border-2 border-teal text-teal font-bold py-3 rounded-lg hover:bg-teal-light transition-colors text-sm"
              >
                Request changes
              </button>
            </div>
          )}

          {changeMode && !submitted && (
            <form onSubmit={handleChangeSubmit} className="space-y-3">
              <textarea
                value={changeText}
                onChange={e => setChangeText(e.target.value)}
                placeholder="Describe the changes you'd like — e.g. 'Can we add a second status LED on GPIO5?' or 'The board needs to be under 50mm wide.'"
                rows={4}
                required
                className="w-full border-2 border-teal-light rounded-xl p-3 text-sm focus:outline-none focus:border-teal transition-colors resize-none placeholder:text-light-grey"
              />
              <div className="flex gap-3">
                <button
                  type="submit"
                  className="flex-1 bg-teal text-white font-bold py-2.5 rounded-lg hover:bg-[#0c3335] transition-colors text-sm"
                >
                  Send request
                </button>
                <button
                  type="button"
                  onClick={() => setChangeMode(false)}
                  className="px-4 text-mid-grey text-sm hover:text-near-black transition-colors"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {submitted && (
            <div className="bg-teal-light border border-teal rounded-xl p-4 text-sm text-teal">
              <p className="font-bold mb-1">Change request received.</p>
              <p>Our engineer will update the design and send you a new review link, usually within 4 hours.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
