"use client";

import { useEffect, useState } from "react";

interface Props {
  jobId: string;
}

export function SvgViewer({ jobId }: Props) {
  const [svgUrl, setSvgUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("eisla_token");
    fetch(`/api/jobs/${jobId}/preview.svg`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.blob();
      })
      .then((blob) => setSvgUrl(URL.createObjectURL(blob)))
      .catch(() => setError(true));
  }, [jobId]);

  if (error) return null;
  if (!svgUrl)
    return (
      <div className="bg-white rounded-xl p-8 text-center text-dark-light">
        Loading preview...
      </div>
    );

  return (
    <div className="bg-white rounded-xl p-4 shadow-sm overflow-auto">
      <img
        src={svgUrl}
        alt="Board layout preview"
        className="max-w-full mx-auto"
      />
    </div>
  );
}
