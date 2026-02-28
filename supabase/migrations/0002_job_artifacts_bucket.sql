-- Migration 0002: Job artifacts storage bucket + designs.resolved column
--
-- Run in Supabase dashboard SQL editor for project htinhlmybmkacfhjhvck.
--
-- Creates:
--   1. Storage bucket 'job-artifacts' for SVG previews, ZIPs, and job files
--   2. RLS policy: customers can read their own job artifacts
--   3. Service-role can write (used by worker.js)

-- ─── Storage bucket ──────────────────────────────────────────────────────────

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'job-artifacts',
  'job-artifacts',
  false,
  52428800, -- 50 MB max file size
  ARRAY['application/json', 'image/svg+xml', 'application/zip']
)
ON CONFLICT (id) DO NOTHING;

-- Customers can read files in their own design folder
CREATE POLICY "customers_read_own_artifacts"
  ON storage.objects FOR SELECT
  USING (
    bucket_id = 'job-artifacts'
    AND auth.uid() IN (
      SELECT customer_id FROM public.designs
      WHERE id = (storage.foldername(name))[1]::uuid
    )
  );

-- Service-role inserts (worker.js uploads) — no RLS policy needed,
-- service-role key bypasses RLS.

-- ─── Ensure designs.resolved column exists ───────────────────────────────────
-- (Should already exist from 0001, but be safe)

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'designs' AND column_name = 'resolved'
  ) THEN
    ALTER TABLE public.designs ADD COLUMN resolved jsonb;
  END IF;
END$$;
