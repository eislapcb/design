"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useJobStatus } from "@/lib/useJobStatus";
import { StatusBadge } from "@/components/StatusBadge";
import { SvgViewer } from "@/components/SvgViewer";
import { PlacementReview } from "@/components/PlacementReview";

const SHOW_PREVIEW = new Set([
  "awaiting_placement_approval",
  "routing",
  "packaging",
  "files_ready",
  "complete",
]);

export default function JobPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const { data, error, refresh } = useJobStatus(id);

  if (authLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-dark-light">
        Loading...
      </div>
    );
  }

  if (!user) {
    router.push("/login");
    return null;
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      <button
        onClick={() => router.push("/dashboard")}
        className="text-teal hover:text-copper transition-colors font-medium mb-6 inline-block"
      >
        &larr; Back to designs
      </button>

      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm mb-6">
          {error}
        </div>
      )}

      {data && (
        <>
          <div className="flex items-center gap-4 mb-6">
            <h1 className="text-2xl font-bold text-teal">Design</h1>
            <StatusBadge status={data.status} />
          </div>

          <div className="text-sm text-dark-light mb-6">
            Last updated:{" "}
            {new Date(data.updatedAt).toLocaleString("en-GB")}
          </div>

          {/* Status-specific messages */}
          {["paid", "validating", "placing", "routing", "packaging"].includes(
            data.status
          ) && (
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 mb-6">
              <p className="text-blue-700">
                Your design is being processed. This page updates automatically.
              </p>
            </div>
          )}

          {data.status === "awaiting_engineer_review" && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-6 mb-6">
              <p className="text-yellow-700">
                Our engineers are reviewing your design. You&apos;ll be notified
                when it&apos;s ready.
              </p>
            </div>
          )}

          {/* SVG preview */}
          {SHOW_PREVIEW.has(data.status) && (
            <div className="mb-6">
              <SvgViewer jobId={id} />
            </div>
          )}

          {/* Placement approval gate */}
          {data.status === "awaiting_placement_approval" && (
            <div className="mb-6">
              <PlacementReview jobId={id} onApproved={refresh} />
            </div>
          )}

          {/* Download */}
          {data.status === "files_ready" || data.status === "complete" ? (
            <div className="bg-green-50 border border-green-200 rounded-xl p-6">
              <h3 className="font-semibold text-green-800 mb-2">
                Your files are ready
              </h3>
              <p className="text-sm text-green-700 mb-4">
                Download your complete design package including Gerber files,
                bill of materials, and assembly instructions.
              </p>
              <a
                href={`/api/jobs/${id}/download`}
                className="inline-block bg-copper hover:bg-copper-light text-white px-6 py-2 rounded-lg font-medium transition-colors"
              >
                Download files
              </a>
            </div>
          ) : null}

          {data.status === "failed" && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-6">
              <h3 className="font-semibold text-red-800 mb-2">
                Something went wrong
              </h3>
              <p className="text-sm text-red-700">
                There was an issue processing your design. Our team has been
                notified and will be in touch.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
