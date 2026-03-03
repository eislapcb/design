"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "./api";

interface JobStatus {
  designId: string;
  status: string;
  updatedAt: string;
}

const TERMINAL = new Set(["files_ready", "complete", "failed"]);
const POLL_MS = 5000;

export function useJobStatus(jobId: string) {
  const [data, setData] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await apiFetch<{ success: boolean } & JobStatus>(
        `/api/jobs/${jobId}/status`
      );
      if (res.success) {
        setData({
          designId: res.designId,
          status: res.status,
          updatedAt: res.updatedAt,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get status");
    }
  }, [jobId]);

  useEffect(() => {
    refresh();
    const id = setInterval(() => {
      if (data && TERMINAL.has(data.status)) return;
      refresh();
    }, POLL_MS);
    return () => clearInterval(id);
  }, [refresh, data]);

  return { data, error, refresh };
}
