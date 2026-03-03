"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export function Hero() {
  const { user } = useAuth();

  return (
    <section className="max-w-4xl mx-auto px-6 py-24 text-center">
      <h1 className="text-5xl font-bold text-teal leading-tight mb-6">
        Custom electronics,
        <br />
        <span className="text-copper">described in plain English</span>
      </h1>
      <p className="text-lg text-dark-light max-w-2xl mx-auto mb-10">
        Tell us what your board needs to do. We&apos;ll handle the component
        selection, circuit design, and manufacturing — you get a working board
        delivered to your door.
      </p>
      <div className="flex gap-4 justify-center">
        <Link
          href={user ? "/wizard" : "/register"}
          className="bg-copper hover:bg-copper-light text-white px-8 py-3 rounded-lg text-lg font-medium transition-colors"
        >
          Start your design
        </Link>
        {!user && (
          <Link
            href="/login"
            className="border-2 border-teal text-teal hover:bg-teal hover:text-cream px-8 py-3 rounded-lg text-lg font-medium transition-colors"
          >
            Sign in
          </Link>
        )}
      </div>

      <div className="mt-20 grid grid-cols-3 gap-8 text-left">
        <div className="bg-white rounded-xl p-6 shadow-sm">
          <div className="text-2xl mb-3">1</div>
          <h3 className="font-semibold text-teal mb-2">Describe</h3>
          <p className="text-sm text-dark-light">
            Tell us what your board should do in everyday language. No
            engineering knowledge needed.
          </p>
        </div>
        <div className="bg-white rounded-xl p-6 shadow-sm">
          <div className="text-2xl mb-3">2</div>
          <h3 className="font-semibold text-teal mb-2">Review</h3>
          <p className="text-sm text-dark-light">
            We select the right components and design the circuit. You review
            and approve the layout.
          </p>
        </div>
        <div className="bg-white rounded-xl p-6 shadow-sm">
          <div className="text-2xl mb-3">3</div>
          <h3 className="font-semibold text-teal mb-2">Receive</h3>
          <p className="text-sm text-dark-light">
            Your custom board is manufactured and shipped. Full design files
            included.
          </p>
        </div>
      </div>
    </section>
  );
}
