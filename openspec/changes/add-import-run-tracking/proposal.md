## Why

The XLSX import has no server-side memory of what it did. Each request is
independent, the summary exists only in the SSE stream, and once the browser tab
closes there is no record that an import ever happened.

Two consequences, and the second is the one that matters for patient data.

**Resume is per-browser.** The frontend's `import-run-control` change persists a
resume manifest in `localStorage`. That is lost if the user switches machines,
uses a different browser, or clears storage, and it is invisible to anyone else —
including whoever has to work out what happened if the first person is
unavailable mid-migration.

**There is no audit trail.** The real migration is ~8,000 patient dental cards.
Months from now, "what did that import actually do, and who ran it" has no answer
beyond `created_at` timestamps on the rows themselves. For clinical records that
is a gap worth closing while the work is fresh.

There is also a smaller, concrete defect this fixes. The concurrency slot added
in `fix/align-import-with-run-control` is scoped to a *request*, but a run is
~160 requests. Two people importing simultaneously cannot corrupt anything, but
they can interleave between batches and both be refused part-way. A run
identifier is what lets the slot be scoped to the run instead.

## What Changes

- New `import_runs` table recording one row per run: who started it, when, how it
  ended, and the aggregate counters.
- `POST /api/import/xlsx` accepts an optional `run_id` form field. Supplied, the
  request is attributed to that run and the run's totals accumulate across
  batches. Omitted, the endpoint behaves exactly as it does today.
- The concurrency slot is keyed by `run_id`. A second batch of the *same* run is
  never refused; a batch of a *different* run still gets the existing `429`.
- New read endpoints: `GET /api/import/runs` and `GET /api/import/runs/{id}`,
  admin-only, for the audit trail.
- Run status is written from `_finish_run`, the background task that already
  knows how a request ended — completion, fatal error, or client disconnect.

Explicitly **not** in this change, with reasons in `design.md`:

- No `import_run_files` table, so no true cross-device resume yet.
- No `import_run_id` column on `patients` or `visits`.
- No replacement of the in-process `_ImportSlot` with a database lock.

## Capabilities

### New Capabilities
- `import-run-tracking`: a durable record of each XLSX import run — its operator,
  timing, outcome and totals — plus run-scoped concurrency for the batched
  requests that make up one run.

### Modified Capabilities
- `import-xlsx`: gains an optional `run_id` request field and run-scoped rather
  than request-scoped concurrency. Every existing response shape, counter and
  event is unchanged.

## Impact

- **Model**: new `app/models/import_run.py`. `create_all()` handles a brand-new
  table with no hand-rolled DDL, which is the main reason this change stops where
  it does.
- **Router**: `app/routers/import_xlsx.py` — accept `run_id`, key `_ImportSlot`
  by it, write run state in `_finish_run`. New `app/routers/import_runs.py` for
  the read endpoints.
- **Schemas**: new `app/schemas/import_run.py`.
- **Database**: one new table. No `ALTER TABLE`, no change to
  `run_startup_migrations()`.
- **Frontend**: needs to generate a `run_id` per run and send it with every
  batch. Until it does, nothing breaks — the field is optional and its absence
  reproduces today's behaviour exactly.
- **Permissions**: reuses `Permission.ADMIN_IMPORT`; no new permission.
