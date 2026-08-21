## Context

`POST /api/import/xlsx` streams Server-Sent Events and holds all its state in
memory for the length of one request. The frontend's `import-run-control` change
turned one logical import into many requests — 50 files each, so ~160 for the
real 8,000-card migration — with Cancel, Resume and per-batch retry layered on
top in the client. The server still sees 160 unrelated requests.

Two constraints shape everything below.

**There is no Alembic.** `run_startup_migrations()` in `app/main.py` runs
`Base.metadata.create_all()` plus hand-rolled DDL on every boot. `create_all()`
adds tables that do not exist and skips ones that do — so a **new table is free**
and a **new column on an existing table is not**, needing an explicit
`ALTER TABLE ... IF NOT EXISTS` in that function. CLAUDE.md already records that
this startup DDL is the ceiling on rollback: a deploy can be rolled back, the
schema it changed on the way up cannot.

**The frontend's contract is load-bearing.** It reads every counter in
`_empty_counts()` and classifies each file from them. Adding a counter is safe;
removing or renaming one is not. Nothing in this change touches those.

## Goals / Non-Goals

**Goals**
- A durable, queryable answer to "what did this import do, and who ran it".
- Scope the concurrency slot to a run rather than a request, removing the
  interleaving hole documented in CLAUDE.md.
- Cost nothing when the client does not participate: no `run_id`, no behaviour
  change.
- Stay inside `create_all()` — no hand-rolled DDL in this change.

**Non-Goals**
- Cross-device resume. It needs per-file records; see Decision 5.
- Per-record provenance (`import_run_id` on `patients`/`visits`); see Decision 6.
- Undoing a run.
- Replacing `_ImportSlot` with a database lock; see Decision 7.
- Alembic. Still worth doing, still out of scope here.

## Decisions

**1. One table, `import_runs`, and nothing else in this change.**

`create_all()` gives us a new table with no migration machinery, which is the
whole reason this scope is cheap. Every deferred item below is deferred because
it needs either a column on an existing table or a frontend contract we have not
agreed yet. Shipping the audit trail first is worth more than shipping all of it
later, and nothing here forecloses the rest.

**2. Structural fields as columns, counters as `JSONB`.**

```
id            String(36) PK
started_by    String(36) FK users.id      -- who ran it
started_at    DateTime
last_activity DateTime                    -- heartbeat, see Decision 4
finished_at   DateTime NULL
status        Enum(running/completed/cancelled/failed)
total_files   Integer NULL                -- client's declared run size, if known
files_processed Integer
counters      JSONB                       -- the _empty_counts() keys, summed
errors        JSONB                       -- accumulated error strings
```

Counters go in `JSONB` rather than seven typed columns specifically *because*
there is no Alembic. The counter set has already changed once this year —
`patients_updated` was added — and each future addition would otherwise be
another hand-rolled `ALTER TABLE` in `run_startup_migrations()`. Postgres `JSONB`
stays queryable (`counters->>'visits_created'`) and costs nothing to extend.

The structural fields stay real columns: they are filtered and sorted on, they
never change shape, and `started_by` wants a foreign key.

**3. `run_id` is client-supplied and optional.**

The client generates one per run (a UUID) and sends it as a form field with every
batch. Server-side it is upserted on first sight.

Client-supplied rather than server-issued because a run *starts* at the first
batch and the client already owns run identity for its `localStorage` manifest.
Issuing ids server-side would need a separate "start run" call before the first
upload, which is a round trip and a new failure mode for no gain.

Optional because it keeps this change non-breaking. A request without `run_id`
behaves exactly as today, so the API can merge before the frontend adopts it, and
`curl` against the endpoint keeps working.

The id is untrusted input: validate it as a UUID and scope every lookup to a run
the caller started. A client cannot append to somebody else's run.

**4. The slot is keyed by `run_id`, with the heartbeat it already has.**

`_ImportSlot` currently holds a token per request. It gains the run id: a request
whose `run_id` matches the current holder is admitted; any other run gets the
existing `429`. A request with no `run_id` keeps today's per-request semantics.

This closes the interleaving hole — batch 41 of a run can never be refused
because of batch 40 of the same run — and it is the direct fix for the caveat
CLAUDE.md records.

It does mean the slot must survive *between* batches, where today it is released
at the end of each. That is what `last_activity` is for, and the staleness
machinery already exists: `IMPORT_STALE_AFTER_SECONDS` would drop from 300 to
something matched to the gap between batches (a few seconds of upload, not
minutes). A run whose client vanishes stops blocking others once it goes stale.

**5. No `import_run_files`, so no cross-device resume yet.**

True resume needs a per-file record — which files of this run have landed — and
that needs a *stable file identity* the client can send. Filename alone is not
it; the practical candidate is name + size + last-modified, which is a frontend
contract we have not designed. It is also 8,000 rows per run rather than one.

Worth doing, but it is a second change with a real design question in it, and the
audit trail does not depend on it. The frontend's `localStorage` manifest keeps
working meanwhile.

**6. No `import_run_id` on `patients` or `visits`.**

This is the highest-value item and the highest-cost one. It would answer "which
run created this record" and make undo possible.

Two reasons it waits. It needs `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in
`run_startup_migrations()`, which is exactly the pattern CLAUDE.md flags as the
rollback ceiling — and doing it for the first time on the same deploy that
introduces run tracking doubles the risk of both. And its semantics are not
obvious: a patient *found* by a run was not created by it, so a single
`import_run_id` on `patients` would be misleading for exactly the re-import case
the migration will produce most of.

**7. `_ImportSlot` stays in-process.**

A `status='running'` row is tempting as a cross-process lock, and it would fix
the `--workers 1` limitation. It also *reintroduces* the problem the in-process
slot gets for free: a crashed process clears an in-memory lock and does not clear
a database row. That trade is worth making deliberately, with the heartbeat and
takeover logic proven first, not as a side effect of adding an audit table.

**8. Terminal status is written from `_finish_run`.**

The background task added in `fix/align-import-with-run-control` already runs on
every ending a request has — completion, fatal error, and client disconnect — and
already distinguishes them via `run_state["reached_end"]`. It is the natural and
only correct place to write `finished_at` and `status`; there is no other hook
that fires on a disconnect.

Note a run is many requests, so a *batch* ending normally does not end the run.
`status` stays `running` until either the client marks the run finished or
staleness closes it out. That needs one explicit decision at implementation time:
either the client sends a "last batch" flag, or a run is closed by a sweep once
`last_activity` goes cold. The sweep is more robust — it also closes runs whose
client never came back — and needs no further frontend contract.

## Risks / Trade-offs

- **Runs stuck in `running`.** A crashed server or an abandoned client leaves a
  row that never reaches a terminal status. Mitigated by `last_activity` plus a
  staleness rule, which is needed for the slot anyway. Accepted: a stale-closed
  run is marked `cancelled`, not `completed`.
- **Extra writes.** One upsert per batch, ~160 per migration. Negligible against
  the per-file work already happening.
- **`JSONB` counters are weaker than columns** for aggregate queries. Accepted
  deliberately: without Alembic, the schema flexibility is worth more than the
  query ergonomics, and Postgres can still index and query `JSONB` if that
  changes.
- **The frontend has to adopt `run_id` for any of this to record anything.**
  Until it does, the table stays empty and no behaviour changes. That is the
  intended incremental path, but it means the audit trail is not real until both
  repos ship.
- **Scope discipline.** Decisions 5 and 6 are the parts people will want. Writing
  them down as explicit non-goals is what stops this change growing into a
  schema-migration project during a live data migration.

## Open Questions

1. **Run completion**: client-signalled last batch, or staleness sweep? The sweep
   is recommended above but the client already knows, and knowing is cheaper than
   inferring.
2. **Retention**: do runs live forever? One row per run is negligible, so the
   default answer is yes — but it is a patient-adjacent record and worth an
   explicit decision rather than a default.
3. **Should `total_files` be trusted?** The client declares the whole run's size
   in the first batch. It is useful for progress reporting on the audit view, but
   it is a claim, not an observation.
