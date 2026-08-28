-- ==============================================================================
-- Trace Dispatch: Database & Storage Schema
-- Run this SQL in your Supabase Project -> SQL Editor
-- (100% Safe to run multiple times / Idempotent)
-- ==============================================================================

-- 1. Create or Migrate the dispatches table (with 8-character string ID, 7-day retention & save flag)
CREATE TABLE IF NOT EXISTS public.dispatches (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    audio_url TEXT NOT NULL,
    storage_path TEXT,
    duration NUMERIC(6, 2) NOT NULL DEFAULT 0.0,
    transcribed BOOLEAN NOT NULL DEFAULT FALSE,
    transcript TEXT,
    saved BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Migration queries if you already created the table previously:
ALTER TABLE public.dispatches ALTER COLUMN id DROP IDENTITY IF EXISTS;
ALTER TABLE public.dispatches ALTER COLUMN id TYPE TEXT;
ALTER TABLE public.dispatches ADD COLUMN IF NOT EXISTS storage_path TEXT;
ALTER TABLE public.dispatches ADD COLUMN IF NOT EXISTS saved BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.dispatches ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- 2. Create indices for high-performance queries, real-time indexing, and retention purges
CREATE INDEX IF NOT EXISTS idx_dispatches_created_at ON public.dispatches (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dispatches_transcribed ON public.dispatches (transcribed);
CREATE INDEX IF NOT EXISTS idx_dispatches_saved ON public.dispatches (saved);

-- 3. Enable Row Level Security (RLS)
ALTER TABLE public.dispatches ENABLE ROW LEVEL SECURITY;

-- 4. Create policies to allow public anon read, insert, and update
DROP POLICY IF EXISTS "Allow public read access on dispatches" ON public.dispatches;
CREATE POLICY "Allow public read access on dispatches"
    ON public.dispatches FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "Allow public insert on dispatches" ON public.dispatches;
CREATE POLICY "Allow public insert on dispatches"
    ON public.dispatches FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public update on dispatches" ON public.dispatches;
CREATE POLICY "Allow public update on dispatches"
    ON public.dispatches FOR UPDATE
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public delete on dispatches" ON public.dispatches;
CREATE POLICY "Allow public delete on dispatches"
    ON public.dispatches FOR DELETE
    USING (true);

-- 5. Enable Realtime on the dispatches table (safely without throwing error if already added)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables 
        WHERE pubname = 'supabase_realtime' 
          AND schemaname = 'public' 
          AND tablename = 'dispatches'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.dispatches;
    END IF;
END $$;

-- ==============================================================================
-- Supabase Storage Bucket Setup
-- ==============================================================================
INSERT INTO storage.buckets (id, name, public)
VALUES ('dispatch-clips', 'dispatch-clips', true)
ON CONFLICT (id) DO UPDATE SET public = true;

-- Policies for dispatch-clips storage bucket
DROP POLICY IF EXISTS "Public Read Access on dispatch-clips" ON storage.objects;
CREATE POLICY "Public Read Access on dispatch-clips"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'dispatch-clips');

DROP POLICY IF EXISTS "Allow Uploads to dispatch-clips" ON storage.objects;
CREATE POLICY "Allow Uploads to dispatch-clips"
    ON storage.objects FOR INSERT
    WITH CHECK (bucket_id = 'dispatch-clips');

DROP POLICY IF EXISTS "Allow Updates to dispatch-clips" ON storage.objects;
CREATE POLICY "Allow Updates to dispatch-clips"
    ON storage.objects FOR UPDATE
    USING (bucket_id = 'dispatch-clips');

DROP POLICY IF EXISTS "Allow Deletes to dispatch-clips" ON storage.objects;
CREATE POLICY "Allow Deletes to dispatch-clips"
    ON storage.objects FOR DELETE
    USING (bucket_id = 'dispatch-clips');

-- ==============================================================================
-- 6. Server-Side Dashboard Passcode Authentication (RPC)
-- ==============================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION public.verify_dashboard_passcode(candidate_passcode TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    -- SHA-256 hash of 'livedispatch'
    expected_hash TEXT := 'cbe1190a222aeea42cb0c186cfc710016bc458ce7ae32a4a04cd5d75f8d345f5';
BEGIN
    IF candidate_passcode IS NULL THEN
        RETURN FALSE;
    END IF;
    RETURN encode(digest(candidate_passcode, 'sha256'), 'hex') = expected_hash;
END;
$$;

GRANT EXECUTE ON FUNCTION public.verify_dashboard_passcode(TEXT) TO anon, authenticated;

-- ==============================================================================
-- 7. App Configuration Store (Groq API Key & Settings Persistence)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS public.app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.app_config ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow public read on app_config" ON public.app_config;
CREATE POLICY "Allow public read on app_config"
    ON public.app_config FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "Allow public insert/update on app_config" ON public.app_config;
CREATE POLICY "Allow public insert/update on app_config"
    ON public.app_config FOR ALL
    USING (true)
    WITH CHECK (true);
