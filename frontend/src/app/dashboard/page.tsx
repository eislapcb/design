"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { DesignCard } from "@/components/DesignCard";
import type { Design } from "@/lib/types";

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [designs, setDesigns] = useState<Design[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.push("/login");
      return;
    }
    apiFetch<{ designs: Design[] }>("/api/account/designs")
      .then((res) => setDesigns(res.designs))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [user, authLoading, router]);

  if (authLoading || loading) {
    return (
      <div className="flex items-center justify-center py-24 text-dark-light">
        Loading...
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-2xl font-bold text-teal">My designs</h1>
        <Link
          href="/wizard"
          className="bg-copper hover:bg-copper-light text-white px-6 py-2 rounded-lg font-medium transition-colors"
        >
          New design
        </Link>
      </div>

      {designs.length === 0 ? (
        <div className="bg-white rounded-xl p-12 text-center shadow-sm">
          <p className="text-dark-light mb-4">
            You haven&apos;t created any designs yet.
          </p>
          <Link
            href="/wizard"
            className="text-copper hover:underline font-medium"
          >
            Start your first design
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {designs.map((d) => (
            <DesignCard key={d.id} design={d} />
          ))}
        </div>
      )}
    </div>
  );
}
