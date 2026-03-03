"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";

interface Props {
  jobId: string;
  onApproved: () => void;
}

export function PlacementReview({ jobId, onApproved }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleApprove = async () => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/api/jobs/${jobId}/approve-placement`, {
        method: "POST",
      });
      onApproved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-6">
      <h3 className="font-semibold text-amber-800 mb-2">
        Your approval is needed
      </h3>
      <p className="text-sm text-amber-700 mb-4">
        We&apos;ve placed all components on the board. Please review the layout
        above and approve to continue with trace routing.
      </p>
      {error && (
        <div className="mb-4 text-sm text-red-600">{error}</div>
      )}
      <button
        onClick={handleApprove}
        disabled={loading}
        className="bg-copper hover:bg-copper-light disabled:opacity-50 text-white px-6 py-2 rounded-lg font-medium transition-colors"
      >
        {loading ? "Approving..." : "Approve layout"}
      </button>
    </div>
  );
}
