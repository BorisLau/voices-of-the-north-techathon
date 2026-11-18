# Supabase staging with GitHub

## Current project

- Organization: `Voices of the North`
- Project: `voices-of-the-north-staging`
- Project ref: `cxmfmnaadpeyzdzcapqk`
- Region: Southeast Asia (Singapore)
- Database access: FastAPI via the Supabase session pooler
- Audio: local file storage for this prototype; PostgreSQL stores metadata only

The FastAPI application, not the browser, owns the database connection. The
Data API does not automatically expose new tables.

## Database responsibilities

| Table | Purpose |
| --- | --- |
| `records` | Recording metadata, transcript segments, scope, ownership and review state |
| `consent_log` | Append-only consent evidence |
| `audit_log` | Operational actions |
| `deletion_events` | Evidence that audio and text were deleted |
| `corrections` | Proposed transcript or metadata corrections |
| `story_versions` | Approved content history |
| `withdrawals` | Public-visibility withdrawal state |
| `users` | Demo-stage application accounts and roles |
| `auth_codes` | Temporary codes used by the demo login only |
| `card_selections` | Experimental story-card choices |
| `metadata_reviews` | Classifier suggestions and human confirmation |
| `questions` | Ask-a-Story questions and linked answers |

All tables have Row Level Security enabled. The prototype backend connects as the
project database owner through the server-only connection string. Browser access
does not receive this credential.

Audio remains outside PostgreSQL. It is written under `VTN_RECORDS_DIR` so a
future Render persistent disk can replace the local directory without moving
large binary objects into database rows.

## GitHub-managed migrations

Schema changes belong in `supabase/migrations` and must be committed to Git.
Do not create production changes only through the Dashboard.

Create a migration:

```bash
npx --yes supabase@latest migration new describe_change
```

Apply all pending migrations to the hosted project:

```bash
export VTN_DATABASE_URL="$(security find-generic-password \
  -a voices-of-the-north-staging \
  -s voices-of-the-north-supabase-dsn \
  -w)"

npx --yes supabase@latest db push \
  --remote="$VTN_DATABASE_URL" \
  --include-all \
  --skip-vault \
  --yes
```

The connection string is stored in the macOS Keychain and must never be
committed. Prefer hosting secrets for a deployed service.

The Supabase GitHub integration is connected to
`BorisLau/voices-of-the-north-techathon`. During prototype development, its
production branch is `codex/supabase-github-integration`. After this branch is
reviewed and merged, switch the integration branch to `main`.

Free-plan GitHub integration applies migrations when the configured branch is
updated. Preview databases for pull requests require Supabase Pro; they are not
part of this prototype.

## Run the database-connected app locally

```bash
export VTN_DATABASE_URL="$(security find-generic-password \
  -a voices-of-the-north-staging \
  -s voices-of-the-north-supabase-dsn \
  -w)"
export VTN_DATABASE_REQUIRED=1
export VTN_SECRET="replace-with-a-stable-random-secret"

python -m uvicorn server:app --host 127.0.0.1 --port 8001
```

Check:

```bash
curl http://127.0.0.1:8001/api/health
```

Expected database fields:

```json
{
  "storage_ready": true,
  "database_backend": "supabase"
}
```

## Seed a local case

With the database-connected API running on port 8001:

```bash
python tools/seed_supabase_sample.py
```

The script uses the actual API to ensure this sequence succeeds:

1. Demo contributor login.
2. Consent written before record creation.
3. Private `records` row and local audio.
4. Submission with transcript confirmation.
5. Reviewer approval and public projection.

It is safe to rerun; an existing sample record is not duplicated.

## Operating boundaries

- The GitHub integration deploys database migrations; it does not deploy the
  FastAPI application.
- Back up Supabase PostgreSQL and the audio disk separately.
- The Free project may pause after a week without activity. Upgrade to Pro if
  invited acceptance cannot tolerate that.
- Demo login is not invited production authentication. Google OIDC and an
  allowlist remain required before real participant onboarding.
