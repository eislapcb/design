'use client'

import Link from 'next/link'
import { projects } from '@/lib/mock-data'
import type { Project, ProjectStatus } from '@/lib/types'

// ── Status config ─────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<ProjectStatus, string> = {
  submitted:          'Submitted',
  in_design:          'In Design',
  in_review:          'Engineer Review',
  awaiting_approval:  'Awaiting Your Approval',
  manufacturing:      'Manufacturing',
  delivered:          'Delivered',
}

// Colors follow brand guidelines: teal, copper, neutrals only
const STATUS_STYLE: Record<ProjectStatus, string> = {
  submitted:          'bg-teal-light text-teal',
  in_design:          'bg-teal-light text-teal',
  in_review:          'bg-teal-light text-teal',
  awaiting_approval:  'bg-copper-light text-copper font-bold',   // action needed
  manufacturing:      'bg-teal-light text-teal',
  delivered:          'bg-off-white text-mid-grey',
}

const TIER_LABEL: Record<1 | 2 | 3, string> = {
  1: 'Tier 1 — Simple MCU',
  2: 'Tier 2 — Standard MCU',
  3: 'Tier 3 — Advanced MCU',
}

function StatusBadge({ status }: { status: ProjectStatus }) {
  return (
    <span className={`inline-block px-2.5 py-1 rounded text-xs font-mono tracking-wide ${STATUS_STYLE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  )
}

function ActionButton({ project }: { project: Project }) {
  if (project.status === 'awaiting_approval') {
    return (
      <Link
        href={`/review/${project.id}`}
        className="inline-block bg-copper text-white text-sm font-bold px-4 py-2 rounded hover:bg-[#b36c38] transition-colors"
      >
        Review design →
      </Link>
    )
  }
  if (project.status === 'in_review') {
    return (
      <span className="text-sm text-mid-grey">Engineer reviewing — we&apos;ll email you.</span>
    )
  }
  if (project.status === 'manufacturing') {
    return (
      <span className="text-sm text-mid-grey">In production. Estimated 8–12 days.</span>
    )
  }
  if (project.status === 'delivered') {
    return (
      <Link
        href={`/quotes/${project.id}`}
        className="text-sm text-copper font-bold hover:underline"
      >
        View order details
      </Link>
    )
  }
  return null
}

function ProjectCard({ project }: { project: Project }) {
  return (
    <div className="bg-white rounded-xl border border-teal-light p-6 flex flex-col gap-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h3 className="font-bold text-teal text-base truncate">{project.name}</h3>
          <p className="text-xs font-mono text-light-grey mt-0.5 uppercase tracking-wider">
            {TIER_LABEL[project.tier]} · {project.mcu}
          </p>
        </div>
        <StatusBadge status={project.status} />
      </div>

      <p className="text-sm text-mid-grey leading-relaxed line-clamp-2">
        {project.description}
      </p>

      <div className="flex items-center justify-between pt-2 border-t border-teal-light">
        <div>
          <span className="text-teal font-bold text-base">£{project.price}</span>
          <span className="text-mid-grey text-xs ml-1">design fee</span>
        </div>
        <ActionButton project={project} />
      </div>

      <p className="text-xs text-light-grey -mt-2">
        Created {new Date(project.createdAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}
      </p>
    </div>
  )
}

// ── Attention banner (for awaiting_approval projects) ─────────────────────────

function AttentionBanner() {
  const pending = projects.filter(p => p.status === 'awaiting_approval')
  if (pending.length === 0) return null

  return (
    <div className="bg-copper-light border border-copper rounded-xl p-4 flex items-start gap-4 mb-8">
      <div className="w-8 h-8 rounded-full bg-copper flex items-center justify-center flex-shrink-0 mt-0.5">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
          <path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
        </svg>
      </div>
      <div className="flex-1">
        <p className="font-bold text-teal text-sm">
          {pending.length === 1 ? 'One design' : `${pending.length} designs`} waiting for your approval
        </p>
        <p className="text-sm text-mid-grey mt-0.5">
          Review and approve to proceed to manufacturing.
        </p>
      </div>
      <Link
        href={`/review/${pending[0].id}`}
        className="flex-shrink-0 bg-copper text-white text-sm font-bold px-4 py-2 rounded hover:bg-[#b36c38] transition-colors"
      >
        Review now →
      </Link>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const active   = projects.filter(p => p.status !== 'delivered')
  const archived = projects.filter(p => p.status === 'delivered')

  return (
    <div className="p-10 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-copper mb-1">Customer Portal</p>
          <h1 className="text-3xl font-bold text-teal">Your Projects</h1>
        </div>
        <Link
          href="/submit"
          className="bg-copper text-white font-bold text-sm px-5 py-2.5 rounded-lg hover:bg-[#b36c38] transition-colors flex items-center gap-2"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New project
        </Link>
      </div>

      <AttentionBanner />

      {/* Active projects */}
      {active.length > 0 && (
        <section className="mb-10">
          <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-copper mb-4">Active</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {active.map(p => <ProjectCard key={p.id} project={p} />)}
          </div>
        </section>
      )}

      {/* Delivered */}
      {archived.length > 0 && (
        <section>
          <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-mid-grey mb-4">Delivered</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {archived.map(p => <ProjectCard key={p.id} project={p} />)}
          </div>
        </section>
      )}
    </div>
  )
}
