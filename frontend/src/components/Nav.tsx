"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export function Nav() {
  const { user, logout } = useAuth();

  return (
    <nav className="bg-teal text-cream px-6 py-4 flex items-center justify-between">
      <Link href="/" className="text-xl font-bold tracking-tight">
        eisla
      </Link>
      <div className="flex items-center gap-4 text-sm">
        {user ? (
          <>
            <Link
              href="/dashboard"
              className="hover:text-copper-light transition-colors"
            >
              My designs
            </Link>
            <Link
              href="/wizard"
              className="bg-copper hover:bg-copper-light text-white px-4 py-2 rounded-lg transition-colors"
            >
              New design
            </Link>
            <button
              onClick={logout}
              className="hover:text-copper-light transition-colors"
            >
              Sign out
            </button>
          </>
        ) : (
          <>
            <Link
              href="/login"
              className="hover:text-copper-light transition-colors"
            >
              Sign in
            </Link>
            <Link
              href="/register"
              className="bg-copper hover:bg-copper-light text-white px-4 py-2 rounded-lg transition-colors"
            >
              Get started
            </Link>
          </>
        )}
      </div>
    </nav>
  );
}
