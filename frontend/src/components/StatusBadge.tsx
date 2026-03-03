"use client";

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  paid:                        { bg: "bg-blue-100",   text: "text-blue-700",   label: "Starting" },
  validating:                  { bg: "bg-blue-100",   text: "text-blue-700",   label: "Validating" },
  placing:                     { bg: "bg-blue-100",   text: "text-blue-700",   label: "Placing" },
  awaiting_engineer_review:    { bg: "bg-yellow-100", text: "text-yellow-700", label: "In review" },
  awaiting_placement_approval: { bg: "bg-amber-100",  text: "text-amber-700",  label: "Your approval needed" },
  routing:                     { bg: "bg-blue-100",   text: "text-blue-700",   label: "Routing" },
  packaging:                   { bg: "bg-blue-100",   text: "text-blue-700",   label: "Packaging" },
  files_ready:                 { bg: "bg-green-100",  text: "text-green-700",  label: "Ready" },
  complete:                    { bg: "bg-green-100",  text: "text-green-700",  label: "Complete" },
  failed:                      { bg: "bg-red-100",    text: "text-red-700",    label: "Failed" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status] || {
    bg: "bg-gray-100",
    text: "text-gray-700",
    label: status,
  };
  return (
    <span
      className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium ${s.bg} ${s.text}`}
    >
      {s.label}
    </span>
  );
}
