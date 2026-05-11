# DropCode

A small P2P-style file sharing app. The browser uploads files directly to Supabase Storage, then Flask stores a short 6-digit pickup code and returns signed download links to receivers.

## Project Structure

```text
api/index.py
templates/index.html
requirements.txt
vercel.json
.env.example
```

## Supabase Setup

Create a private storage bucket named `files`, then run this SQL in the Supabase SQL editor:

```sql
CREATE TABLE file_shares (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  code VARCHAR(6) UNIQUE NOT NULL,
  filename TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_code ON file_shares(code);
CREATE INDEX idx_expires ON file_shares(expires_at);
```

Add storage policies for the `files` bucket:

```sql
CREATE POLICY "Allow anon uploads"
ON storage.objects FOR INSERT TO anon
WITH CHECK (bucket_id = 'files');

CREATE POLICY "Allow service delete"
ON storage.objects FOR DELETE TO service_role
USING (bucket_id = 'files');
```

If upload fails with `new row violates row-level security policy`, run this policy reset in the Supabase SQL editor:

```sql
DROP POLICY IF EXISTS "Allow anon uploads" ON storage.objects;
DROP POLICY IF EXISTS "Allow service delete" ON storage.objects;

CREATE POLICY "Allow anon uploads"
ON storage.objects
FOR INSERT
TO anon
WITH CHECK (bucket_id = 'files');

CREATE POLICY "Allow service delete"
ON storage.objects
FOR DELETE
TO service_role
USING (bucket_id = 'files');
```

Also make sure the storage bucket is named exactly `files`.

## Environment Variables

Copy `.env.example` to `.env` locally or add these variables in Vercel:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_KEY
```

`SUPABASE_ANON_KEY` is exposed to the browser so it can upload directly to Supabase Storage. Keep `SUPABASE_SERVICE_KEY` server-only.

## Run Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
flask --app api.index run --debug
```

Then open `http://127.0.0.1:5000`.

## Deploy

Deploy with Vercel and add the environment variables in the Vercel project settings. The configured cron calls `/api/cleanup` every 5 minutes to remove expired files and database rows.
