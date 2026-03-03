"use client";

import Link from "next/link";
import { StatusBadge } from "./StatusBadge";
import type { Design } from "@/lib/types";

export function DesignCard({ design }: { design: Design }) {
  const date = new Date(design.created_at).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  return (
    <Link
      href={`/jobs/${design.id}`}
      className="block bg-white rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow border border-cream-dark"
    >
      <div className="flex justify-between items-start mb-3">
        <div className="text-sm text-dark-light">{date}</div>
        <StatusBadge status={design.status} />
      </div>
      <p className="text-dark font-medium line-clamp-2">
        {design.description || "Untitled design"}
      </p>
      <div className="mt-3 text-xs text-dark-light">
        Tier {design.tier} &middot; £{(design.design_fee_gbp / 100).toFixed(2)}
      </div>
    </Link>
  );
}
