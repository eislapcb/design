'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

// The Circuit E icon from the brand guidelines, reproduced exactly as on the landing page
function EislaIcon({ size = 36 }: { size?: number }) {
  return (
    <svg viewBox="0 0 80 80" width={size} height={size} xmlns="http://www.w3.org/2000/svg">
      <rect x="12" y="10" width="11" height="60" rx="3" fill="#C27840" />
      <rect x="23" y="10" width="34" height="11" rx="3" fill="#C27840" />
      <rect x="23" y="34.5" width="26" height="11" rx="3" fill="#C27840" />
      <rect x="23" y="59" width="34" height="11" rx="3" fill="#C27840" />
      <circle cx="62" cy="15.5" r="6" fill="#C27840" />
      <circle cx="62" cy="15.5" r="2.5" fill="#0E3D3F" />
      <circle cx="54" cy="40" r="6" fill="#C27840" />
      <circle cx="54" cy="40" r="2.5" fill="#0E3D3F" />
      <circle cx="62" cy="64.5" r="6" fill="#C27840" />
      <circle cx="62" cy="64.5" r="2.5" fill="#0E3D3F" />
    </svg>
  )
}

function DashboardIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  )
}

function PlusIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function NavLink({
  href,
  icon: Icon,
  children,
}: {
  href: string
  icon: React.FC<{ className?: string }>
  children: React.ReactNode
}) {
  const pathname = usePathname()
  const active = pathname === href

  return (
    <Link
      href={href}
      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-bold transition-colors ${
        active
          ? 'bg-copper text-white'
          : 'text-white/60 hover:text-white hover:bg-white/10'
      }`}
    >
      <Icon className="w-4 h-4 flex-shrink-0" />
      {children}
    </Link>
  )
}

export default function Nav() {
  return (
    <aside className="w-60 bg-teal min-h-screen flex flex-col fixed left-0 top-0 z-40">
      {/* Logo lockup — brand guidelines §2.1 */}
      <div className="p-6 border-b border-white/10">
        <Link href="/" className="flex items-center gap-3">
          <EislaIcon size={36} />
          <span
            className="text-white font-bold text-xl tracking-[0.2em] uppercase"
          >
            Eisla
          </span>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        <NavLink href="/" icon={DashboardIcon}>
          Dashboard
        </NavLink>
        <NavLink href="/submit" icon={PlusIcon}>
          New Project
        </NavLink>
      </nav>

      {/* Account — bottom of sidebar */}
      <div className="p-4 border-t border-white/10">
        <div className="flex items-center gap-3 px-3 py-2">
          <div className="w-8 h-8 rounded-full bg-copper flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
            A
          </div>
          <div className="min-w-0">
            <div className="text-white text-sm font-bold truncate">Andy Middleton</div>
            <div className="text-white/40 text-xs truncate">andy@eisla.com</div>
          </div>
        </div>
      </div>
    </aside>
  )
}
